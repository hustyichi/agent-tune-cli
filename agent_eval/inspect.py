from __future__ import annotations

import json
from pathlib import Path

from agent_eval.artifacts import resolve_run


def load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def inspect_run(
    root: Path, run: str, case_id: str | None = None, cluster_id: str | None = None
) -> str:
    run_dir = resolve_run(root, run)
    if not run_dir.exists():
        raise FileNotFoundError(f"Run not found: {run}")
    if case_id:
        evals = load_jsonl(run_dir / "eval_results.jsonl")
        raws = {r["case_id"]: r for r in load_jsonl(run_dir / "raw_results.jsonl")}
        item = next((e for e in evals if e["case_id"] == case_id), None)
        if not item:
            raise FileNotFoundError(f"Case not found: {case_id}")
        return json.dumps(
            {"eval": item, "raw": raws.get(case_id)}, indent=2, ensure_ascii=False
        )
    clusters = json.loads((run_dir / "clusters.json").read_text())
    if cluster_id:
        item = next(
            (c for c in clusters.get("clusters", []) if c["cluster_id"] == cluster_id),
            None,
        )
        if not item:
            raise FileNotFoundError(f"Cluster not found: {cluster_id}")
        return json.dumps(item, indent=2, ensure_ascii=False)
    manifest = json.loads((run_dir / "manifest.json").read_text())
    evals = load_jsonl(run_dir / "eval_results.jsonl")
    total = len(evals)
    passed = sum(1 for e in evals if e.get("passed"))
    return f"Run: {manifest['run_id']}\nProject: {manifest['project']}\nCases: {total}\nPassed: {passed}\nFailed: {total - passed}\nClusters: {len(clusters.get('clusters', []))}\nDirectory: {run_dir}"
