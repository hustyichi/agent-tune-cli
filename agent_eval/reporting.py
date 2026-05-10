from __future__ import annotations

from agent_eval.analysis import build_run_analysis
from agent_eval.models import ClustersFile, EvalCase, EvalResult, FailureRecord, RawResult
from agent_eval.models import AnalysisBucket, ClusterAnalysis, RunAnalysis


def _render_breakdown(title: str, buckets: list[AnalysisBucket]) -> list[str]:
    lines = [f"## {title}", ""]
    if not buckets:
        return lines + ["- none"]
    return lines + [
        f"- {bucket.name}: total={bucket.total}, passed={bucket.passed}, failed={bucket.failed}, pass_rate={bucket.pass_rate:.1f}%"
        for bucket in buckets
    ]


def _render_cluster(cluster: ClusterAnalysis) -> list[str]:
    lines = [
        f"### {cluster.cluster_id}: {cluster.title}",
        "",
        f"- Severity: {cluster.severity}",
        f"- Cases: {', '.join(cluster.cases)}",
        f"- Representative cases: {', '.join(cluster.representative_cases) or 'none'}",
        f"- Common signature: {', '.join(f'{key}={value}' for key, value in cluster.common_signature.items() if key != 'analysis' and value) or 'none'}",
        f"- Signature explanation: {cluster.signature_explanation}",
        f"- Suspected modules: {', '.join(cluster.suspected_modules) if cluster.suspected_modules else 'none identified from local evidence'}",
        f"- Affected areas: {', '.join(cluster.affected_areas) if cluster.affected_areas else 'none identified from local evidence'}",
        f"- Suggested investigation: {cluster.suggested_investigation}",
        "",
        "#### Evidence",
        "",
    ]
    if cluster.evidence:
        lines += [f"- {item.case_id}: {item.reason or 'no reason recorded'}" for item in cluster.evidence]
    else:
        lines.append("- none")
    lines.append("")
    return lines


def render_summary_from_analysis(analysis: RunAnalysis) -> str:
    totals = analysis.totals
    lines = [
        f"# Agent-Eval Summary: {analysis.run_id}",
        "",
        "## Run Summary",
        "",
        f"- Total cases: {totals.total}",
        f"- Passed: {totals.passed}",
        f"- Failed: {totals.failed}",
        f"- Pass rate: {totals.pass_rate:.1f}%",
        f"- Run directory: {analysis.run_dir}",
        "",
    ]
    lines += _render_breakdown("Tag Breakdown", analysis.tag_breakdown)
    lines += [""] + _render_breakdown("Priority Breakdown", analysis.priority_breakdown)
    lines += ["", "## Top Failure Clusters", ""]
    if analysis.clusters:
        for cluster in analysis.clusters[:10]:
            lines += _render_cluster(cluster)
    else:
        lines.append("No failure clusters.")
    return "\n".join(lines).rstrip() + "\n"


def render_summary(run_id: str, cases: list[EvalCase], raw_results: list[RawResult], eval_results: list[EvalResult], failures: list[FailureRecord], clusters: ClustersFile) -> str:
    analysis = build_run_analysis(run_id, cases, raw_results, eval_results, failures, clusters)
    return render_summary_from_analysis(analysis)


def console_summary(run_id: str, eval_results: list[EvalResult], clusters: ClustersFile, run_dir: str) -> str:
    total = len(eval_results)
    passed = sum(1 for r in eval_results if r.passed)
    failed = total - passed
    pass_rate = (passed / total * 100) if total else 0
    top = ", ".join(c.cluster_id for c in clusters.clusters[:3]) or "none"
    return f"Run {run_id}: total={total} passed={passed} failed={failed} pass_rate={pass_rate:.1f}% top_clusters={top} run_dir={run_dir}"
