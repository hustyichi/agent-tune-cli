from __future__ import annotations

from collections import Counter

from agent_eval.models import ClustersFile, EvalCase, EvalResult, FailureRecord, RawResult


def render_summary(run_id: str, cases: list[EvalCase], raw_results: list[RawResult], eval_results: list[EvalResult], failures: list[FailureRecord], clusters: ClustersFile) -> str:
    total = len(eval_results)
    passed = sum(1 for r in eval_results if r.passed)
    failed = total - passed
    pass_rate = (passed / total * 100) if total else 0
    tag_counts = Counter(tag for case in cases for tag in case.tags)
    lines = [
        f"# Agent-Eval Summary: {run_id}",
        "",
        "## Run Summary",
        "",
        f"- Total cases: {total}",
        f"- Passed: {passed}",
        f"- Failed: {failed}",
        f"- Pass rate: {pass_rate:.1f}%",
        f"- Run directory: runs/{run_id}",
        "",
        "## Tags",
        "",
    ]
    if tag_counts:
        lines += [f"- {tag}: {count}" for tag, count in sorted(tag_counts.items())]
    else:
        lines.append("- none")
    lines += ["", "## Top Failure Clusters", ""]
    if clusters.clusters:
        for cluster in clusters.clusters[:10]:
            lines += [f"### {cluster.cluster_id}: {cluster.title}", "", f"- Severity: {cluster.severity}", f"- Cases: {', '.join(cluster.case_ids)}", f"- Summary: {cluster.summary}", ""]
    else:
        lines.append("No failure clusters.")
    return "\n".join(lines) + "\n"


def console_summary(run_id: str, eval_results: list[EvalResult], clusters: ClustersFile, run_dir: str) -> str:
    total = len(eval_results)
    passed = sum(1 for r in eval_results if r.passed)
    failed = total - passed
    pass_rate = (passed / total * 100) if total else 0
    top = ", ".join(c.cluster_id for c in clusters.clusters[:3]) or "none"
    return f"Run {run_id}: total={total} passed={passed} failed={failed} pass_rate={pass_rate:.1f}% top_clusters={top} run_dir={run_dir}"
