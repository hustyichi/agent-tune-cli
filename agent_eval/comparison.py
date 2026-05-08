from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_eval.artifacts import resolve_run
from agent_eval.models import CaseTransition, ClusterTransitions, ComparisonTotals, RunComparison
from agent_eval.utils.redact import redact

CLUSTER_KEY_VERSION = "v1"
CHANGED_CASE_TRANSITIONS = {"passed_to_failed", "failed_to_passed", "added", "removed"}


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Required artifact missing: {path.name}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON artifact {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid JSON artifact {path}: expected object")
    return data


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"Required artifact missing: {path.name}")
    rows: list[dict[str, Any]] = []
    try:
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if not line.strip():
                continue
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError(f"line {lineno} is not an object")
            rows.append(row)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSONL artifact {path}: {exc}") from exc
    return rows


def _run_id(run_dir: Path, fallback: str) -> str:
    manifest_path = run_dir / "manifest.json"
    # Old comparison fixtures may omit manifest.json; the run selector is the
    # explicit fallback identity, while malformed existing manifests still fail.
    if not manifest_path.exists():
        return fallback
    manifest = _load_json(manifest_path)
    raw = manifest.get("run_id") or fallback
    return str(raw)


def _evals_by_case(run_dir: Path) -> dict[str, bool]:
    rows = _load_jsonl(run_dir / "eval_results.jsonl")
    result: dict[str, bool] = {}
    for row in rows:
        if "case_id" not in row or "passed" not in row:
            raise ValueError("eval_results.jsonl entries must include case_id and passed")
        result[str(row["case_id"])] = bool(row["passed"])
    return result


def _cluster_ids(run_dir: Path) -> set[str]:
    data = _load_json(run_dir / "clusters.json")
    clusters = data.get("clusters", [])
    if not isinstance(clusters, list):
        raise ValueError("clusters.json must contain a clusters list")
    ids: set[str] = set()
    for item in clusters:
        if isinstance(item, dict) and item.get("cluster_id"):
            ids.add(str(item["cluster_id"]))
    return ids


def _rate(passed: int, total: int) -> float:
    return (passed / total * 100) if total else 0.0


def _transition(base: bool | None, target: bool | None) -> str:
    if base is None:
        return "added"
    if target is None:
        return "removed"
    if base and target:
        return "unchanged_pass"
    if (not base) and (not target):
        return "unchanged_fail"
    if base and not target:
        return "passed_to_failed"
    return "failed_to_passed"


def compare_runs(root: Path, base: str, target: str) -> RunComparison:
    base_dir = resolve_run(root, base)
    target_dir = resolve_run(root, target)
    base_id = _run_id(base_dir, base)
    target_id = _run_id(target_dir, target)
    base_evals = _evals_by_case(base_dir)
    target_evals = _evals_by_case(target_dir)

    base_passed = sum(1 for value in base_evals.values() if value)
    target_passed = sum(1 for value in target_evals.values() if value)
    base_total = len(base_evals)
    target_total = len(target_evals)
    base_rate = _rate(base_passed, base_total)
    target_rate = _rate(target_passed, target_total)

    case_transitions = [
        CaseTransition(
            case_id=case_id,
            base_passed=base_evals.get(case_id),
            target_passed=target_evals.get(case_id),
            transition=_transition(base_evals.get(case_id), target_evals.get(case_id)),
        )
        for case_id in sorted(set(base_evals) | set(target_evals))
    ]

    base_clusters = _cluster_ids(base_dir)
    target_clusters = _cluster_ids(target_dir)
    comparison = RunComparison(
        base_run_id=base_id,
        target_run_id=target_id,
        cluster_key_version=CLUSTER_KEY_VERSION,
        totals=ComparisonTotals(
            base_total=base_total,
            base_passed=base_passed,
            base_failed=base_total - base_passed,
            base_pass_rate=base_rate,
            target_total=target_total,
            target_passed=target_passed,
            target_failed=target_total - target_passed,
            target_pass_rate=target_rate,
            pass_rate_delta=target_rate - base_rate,
        ),
        case_transitions=case_transitions,
        cluster_transitions=ClusterTransitions(
            added=sorted(target_clusters - base_clusters),
            removed=sorted(base_clusters - target_clusters),
            persisted=sorted(base_clusters & target_clusters),
        ),
        analysis={"cluster_key_version": CLUSTER_KEY_VERSION},
    )
    return RunComparison.model_validate(redact(comparison.model_dump(mode="json")))


def comparison_summary(comparison: RunComparison) -> str:
    totals = comparison.totals
    changed = sum(1 for item in comparison.case_transitions if item.transition in CHANGED_CASE_TRANSITIONS)
    return (
        f"Comparison {comparison.base_run_id} -> {comparison.target_run_id}: "
        f"pass_rate_delta={totals.pass_rate_delta:.1f}pp "
        f"base={totals.base_passed}/{totals.base_total} "
        f"target={totals.target_passed}/{totals.target_total} "
        f"changed_cases={changed} "
        f"clusters_added={len(comparison.cluster_transitions.added)} "
        f"clusters_removed={len(comparison.cluster_transitions.removed)}"
    )
