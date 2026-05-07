from __future__ import annotations

import concurrent.futures
from importlib import resources
from pathlib import Path
from typing import Optional

import typer

from .artifacts import ArtifactStore
from .clustering import cluster_failures, make_failures
from .config import load_config
from .dataset import load_cases
from .evaluators import evaluate_case
from .export import export_repair_input
from .inspect import inspect_run
from .reporting import console_summary, render_summary
from .run_id import new_run_id
from .runners import build_runner

app = typer.Typer(help="Local-first Agent batch evaluation and failure analysis CLI.")


def _copy_template(name: str, dest: Path, overwrite: bool = False) -> None:
    if dest.exists() and not overwrite:
        return
    content = resources.files("agent_eval.templates").joinpath(name).read_text()
    dest.write_text(content)


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

    raw_results = []
    if config.runner.concurrency > 1:
        with concurrent.futures.ThreadPoolExecutor(max_workers=config.runner.concurrency) as pool:
            futures = [pool.submit(runner.run_with_retries, case, run_id, config.runner.retry_times) for case in cases]
            for fut in concurrent.futures.as_completed(futures):
                raw_results.append(fut.result())
    else:
        for case in cases:
            result = runner.run_with_retries(case, run_id, config.runner.retry_times)
            raw_results.append(result)
            if config.runner.fail_fast and result.status != "success":
                break
    case_by_id = {case.id: case for case in cases}
    raw_results.sort(key=lambda r: list(case_by_id).index(r.case_id))
    eval_results = [evaluate_case(run_id, case_by_id[raw.case_id], raw, config.evaluation.llm_judge) for raw in raw_results]
    raw_by_case = {r.case_id: r for r in raw_results}
    failures = make_failures(run_id, eval_results, raw_by_case)
    clusters = cluster_failures(run_id, failures) if config.cluster.enabled else cluster_failures(run_id, [])
    summary = render_summary(run_id, cases, raw_results, eval_results, failures, clusters)
    store.write_all(raw_results, eval_results, failures, clusters, summary)
    typer.echo(console_summary(run_id, eval_results, clusters, str(store.run_dir)))


@app.command()
def inspect(run: str = typer.Option("latest", "--run"), case: Optional[str] = typer.Option(None, "--case"), cluster: Optional[str] = typer.Option(None, "--cluster")) -> None:
    """Inspect a run, case, or failure cluster from local artifacts."""
    try:
        typer.echo(inspect_run(Path("."), run, case, cluster))
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc


@app.command("export")
def export_cmd(run: str = typer.Option("latest", "--run"), show: bool = typer.Option(False, "--show", help="Print JSON content instead of path.")) -> None:
    """Export repair input for downstream tuning tools."""
    try:
        path = Path(export_repair_input(Path("."), run))
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(str(exc), err=True)
        raise typer.Exit(1) from exc
    typer.echo(path.read_text() if show else str(path))
