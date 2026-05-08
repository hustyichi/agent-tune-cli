from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent_eval.comparison import compare_runs


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data) + "\n")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def make_run(root: Path, run_id: str, evals: list[dict], clusters: list[dict]) -> None:
    run_dir = root / "runs" / run_id
    run_dir.mkdir(parents=True)
    write_json(run_dir / "manifest.json", {"run_id": run_id, "project": "demo"})
    write_jsonl(run_dir / "eval_results.jsonl", evals)
    write_json(run_dir / "clusters.json", {"run_id": run_id, "clusters": clusters})


def test_compare_runs_computes_case_and_cluster_transitions(tmp_path: Path):
    make_run(
        tmp_path,
        "base",
        [
            {"run_id": "base", "case_id": "c1", "passed": True},
            {"run_id": "base", "case_id": "c2", "passed": False},
        ],
        [{"cluster_id": "cluster_old"}, {"cluster_id": "cluster_persist"}],
    )
    make_run(
        tmp_path,
        "target",
        [
            {"run_id": "target", "case_id": "c1", "passed": False},
            {"run_id": "target", "case_id": "c2", "passed": True},
            {"run_id": "target", "case_id": "c3", "passed": True},
        ],
        [{"cluster_id": "cluster_new"}, {"cluster_id": "cluster_persist"}],
    )

    comparison = compare_runs(tmp_path, "base", "target")
    dumped = comparison.model_dump(mode="json")

    assert dumped["base_run_id"] == "base"
    assert dumped["target_run_id"] == "target"
    assert dumped["cluster_key_version"] == "v1"
    assert dumped["totals"] == {
        "base_total": 2,
        "base_passed": 1,
        "base_failed": 1,
        "base_pass_rate": 50.0,
        "target_total": 3,
        "target_passed": 2,
        "target_failed": 1,
        "target_pass_rate": pytest.approx(66.6666666667),
        "pass_rate_delta": pytest.approx(16.6666666667),
    }
    transitions = {item["case_id"]: item["transition"] for item in dumped["case_transitions"]}
    assert transitions == {"c1": "passed_to_failed", "c2": "failed_to_passed", "c3": "added"}
    assert dumped["cluster_transitions"] == {
        "added": ["cluster_new"],
        "removed": ["cluster_old"],
        "persisted": ["cluster_persist"],
    }


def test_compare_runs_reads_minimum_old_schema_and_rejects_traversal(tmp_path: Path):
    make_run(tmp_path, "base", [{"run_id": "base", "case_id": "old", "passed": True}], [])
    make_run(tmp_path, "target", [{"run_id": "target", "case_id": "old", "passed": True}], [])

    comparison = compare_runs(tmp_path, "base", "target")
    assert comparison.case_transitions[0].transition == "unchanged_pass"

    with pytest.raises(ValueError):
        compare_runs(tmp_path, "../base", "target")


def test_compare_runs_missing_required_legacy_file_has_clear_error(tmp_path: Path):
    (tmp_path / "runs" / "base").mkdir(parents=True)
    make_run(tmp_path, "target", [], [])

    with pytest.raises(FileNotFoundError, match="eval_results.jsonl"):
        compare_runs(tmp_path, "base", "target")
