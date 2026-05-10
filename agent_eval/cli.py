from __future__ import annotations

import concurrent.futures
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any, Optional

import typer

from .artifacts import ArtifactStore
from .analysis import build_run_analysis
from .clustering import cluster_failures, make_failures
from .comparison import compare_runs, comparison_summary
from .config import load_config
from .dataset import load_cases
from .evaluators import evaluate_case
from .evaluation_policy import attempt_count_for, decide_attempts_pass, select_representative_attempt
from .export import export_repair_input
from .inspect import inspect_run
from .reporting import console_summary, render_summary_from_analysis
from .run_id import new_run_id
from .runners import build_runner
from .runners.base import BaseRunner
from .models import EvalCase, EvalResult, LlmJudgeConfig, RawResult

app = typer.Typer(help="Local-first Agent batch evaluation and failure analysis CLI.")


@dataclass
class CaseRunResult:
    raw: RawResult
    eval: EvalResult
    attempts: list[dict[str, Any]]


def _copy_template(name: str, dest: Path, overwrite: bool = False) -> None:
    if dest.exists() and not overwrite:
        return
    content = resources.files("agent_eval.templates").joinpath(name).read_text()
    dest.write_text(content)


def _with_attempt_metadata(raw: RawResult, attempt_index: int, attempt_count: int) -> RawResult:
    metadata = dict(raw.metadata)
    metadata.update(
        {
            "evaluation_attempt_index": attempt_index,
            "evaluation_attempt_count": attempt_count,
        }
    )
    return raw.model_copy(update={"metadata": metadata}, deep=True)


def _run_case_with_policy(case: EvalCase, runner: BaseRunner, run_id: str, retry_times: int, llm_config: LlmJudgeConfig) -> CaseRunResult:
    total_attempts = attempt_count_for(case)
    raw_attempts = []
    eval_attempts = []
    sidecar_rows = []
    for attempt_index in range(total_attempts):
        raw = _with_attempt_metadata(
            runner.run_with_retries(case, run_id, retry_times),
            attempt_index,
            total_attempts,
        )
        result = evaluate_case(run_id, case, raw, llm_config)
        raw_attempts.append(raw)
        eval_attempts.append(result)
        if total_attempts > 1:
            sidecar_rows.append(
                {
                    "run_id": run_id,
                    "case_id": case.id,
                    "evaluation_attempt_index": attempt_index,
                    "evaluation_attempt_count": total_attempts,
                    "passed": result.passed,
                    "raw_result": raw.model_dump(mode="json"),
                    "eval_result": result.model_dump(mode="json"),
                    "runner_attempt_count": raw.attempt_count,
                }
            )
    attempt_passes = [result.passed for result in eval_attempts]
    aggregate_passed = decide_attempts_pass(attempt_passes, case.evaluation_policy.pass_rule)
    representative_index = select_representative_attempt(attempt_passes, aggregate_passed)
    representative_raw = raw_attempts[representative_index]
    representative_eval = eval_attempts[representative_index]
    canonical_eval = representative_eval.model_copy(update={"passed": aggregate_passed}, deep=True)
    if aggregate_passed:
        canonical_eval.failure_signature = None
    return CaseRunResult(raw=representative_raw, eval=canonical_eval, attempts=sidecar_rows)


@app.command()
def init(path: Path = typer.Argument(Path("."), help="Project directory to initialize."), force: bool = typer.Option(False, "--force", help="Overwrite template files.")) -> None:
    """Initialize a local evaluation project."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "cases").mkdir(exist_ok=True)
    (path / "runs").mkdir(exist_ok=True)
    (path / "reports").mkdir(exist_ok=True)
    _copy_template("eval.yaml", path / "eval.yaml", force)
    _copy_template("sample.jsonl", path / "cases" / "sample.jsonl", force)
    _copy_template("sample_agent.py", path / "sample_agent.py", force)
    typer.echo(f"Initialized Agent-Eval project at {path}")


@app.command()
def run(
    config_path: Path = typer.Option(Path("eval.yaml"), "--config", help="Path to eval.yaml."),
    dataset: Optional[Path] = typer.Option(None, "--dataset", help="Override dataset path."),
    run_name: Optional[str] = typer.Option(None, "--run-name", help="Run id/name."),
    concurrency: Optional[int] = typer.Option(None, "--concurrency", help="Override concurrency."),
) -> None:
    """Run the full local evaluation pipeline."""
    root = config_path.parent if config_path.parent != Path("") else Path(".")
    config = load_config(config_path)
    if dataset is not None:
        config.dataset.paths = [str(dataset)]
    if concurrency is not None:
        config.runner.concurrency = concurrency
    try:
        run_id = new_run_id(run_name)
    except ValueError as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    cases = load_cases(config.dataset.paths, root)
    store = ArtifactStore(root, config, run_id)
    store.prepare()
    runner = build_runner(config, root)

    case_results: list[CaseRunResult] = []
    if config.runner.concurrency > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.runner.concurrency) as pool:
            futures = [pool.submit(_run_case_with_policy, case, runner, run_id, config.runner.retry_times, config.evaluation.llm_judge) for case in cases]
            for fut in concurrent.futures.as_completed(futures):
                case_results.append(fut.result())
    else:
        for case in cases:
            result = _run_case_with_policy(case, runner, run_id, config.runner.retry_times, config.evaluation.llm_judge)
            case_results.append(result)
            if config.runner.fail_fast and not result.eval.passed:
                break
    case_by_id = {case.id: case for case in cases}
    case_order = list(case_by_id)
    case_results.sort(key=lambda r: case_order.index(r.raw.case_id))
    raw_results = [result.raw for result in case_results]
    eval_results = [result.eval for result in case_results]
    attempt_rows = [attempt for result in case_results for attempt in result.attempts]
    raw_by_case = {r.case_id: r for r in raw_results}
    failures = make_failures(run_id, eval_results, raw_by_case)
    clusters = cluster_failures(run_id, failures) if config.cluster.enabled else cluster_failures(run_id, [])
    analysis = build_run_analysis(run_id, cases, raw_results, eval_results, failures, clusters, str(store.run_dir))
    summary = render_summary_from_analysis(analysis)
    store.write_all(cases, raw_results, eval_results, failures, clusters, summary, analysis, attempt_rows)
    typer.echo(console_summary(run_id, eval_results, clusters, str(store.run_dir)))


@app.command()
def inspect(run: str = typer.Option("latest", "--run"), case: Optional[str] = typer.Option(None, "--case"), cluster: Optional[str] = typer.Option(None, "--cluster")) -> None:
    """Inspect a run, case, or failure cluster from local artifacts."""
    try:
        typer.echo(inspect_run(Path("."), run, case, cluster))
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command()
def compare(
    base: str = typer.Option(..., "--base", help="Base run id, or latest."),
    target: str = typer.Option(..., "--target", help="Target run id, or latest."),
    output: Optional[Path] = typer.Option(None, "--output", help="Write machine-readable comparison JSON to this path."),
    show: bool = typer.Option(False, "--show", help="Print machine-readable JSON instead of a human summary."),
) -> None:
    """Compare two local runs."""
    try:
        comparison = compare_runs(Path("."), base, target)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    data = comparison.model_dump_json(indent=2) + "\n"
    if output is not None:
        output.write_text(data)
    typer.echo(data if show else comparison_summary(comparison))


@app.command("export")
def export_cmd(run: str = typer.Option("latest", "--run"), show: bool = typer.Option(False, "--show", help="Print JSON content instead of path.")) -> None:
    """Export repair input for downstream tuning tools."""
    try:
        path = Path(export_repair_input(Path("."), run))
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(path.read_text() if show else str(path))
