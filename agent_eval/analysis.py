from __future__ import annotations

from collections import Counter
from typing import Iterable

from .models import (
    AnalysisBucket,
    AnalysisTotals,
    CaseEvidence,
    ClusterAnalysis,
    ClustersFile,
    EvalCase,
    EvalResult,
    FailureRecord,
    RawResult,
    RunAnalysis,
)
from .utils.redact import redact_text

PRIORITY_ORDER = {"p0": 0, "p1": 1, "p2": 2, "p3": 3, "p4": 4}


def _rate(passed: int, total: int) -> float:
    return (passed / total * 100) if total else 0.0


def _bucket_sort(name: str) -> tuple[int, str]:
    return (PRIORITY_ORDER.get(name.lower(), 100), name)


def _make_bucket(name: str, case_ids: set[str], passed_case_ids: set[str]) -> AnalysisBucket:
    total = len(case_ids)
    passed = len(case_ids & passed_case_ids)
    failed = total - passed
    return AnalysisBucket(name=name, total=total, passed=passed, failed=failed, pass_rate=_rate(passed, total))


def _breakdown(labels_by_case: dict[str, Iterable[str]], passed_case_ids: set[str], *, sort_priority: bool = False) -> list[AnalysisBucket]:
    grouped: dict[str, set[str]] = {}
    for case_id, labels in labels_by_case.items():
        for label in labels:
            grouped.setdefault(label, set()).add(case_id)
    key = _bucket_sort if sort_priority else (lambda value: (0, value))
    return [_make_bucket(name, grouped[name], passed_case_ids) for name in sorted(grouped, key=key)]


def _affected_areas(signature: dict, suspected_modules: list[str]) -> list[str]:
    areas = [f"module:{module}" for module in suspected_modules]
    for field, prefix in (("route_name", "route"), ("tool_name", "tool"), ("error_code", "error"), ("tag", "tag")):
        value = signature.get(field)
        if value:
            areas.append(f"{prefix}:{value}")
    analysis = signature.get("analysis") or {}
    common_root_cause = analysis.get("common_root_cause")
    if common_root_cause:
        areas.append(f"root_cause:{common_root_cause}")
    else:
        for root_cause in analysis.get("root_causes") or []:
            areas.append(f"root_cause:{root_cause}")
    return areas


def _suggested_investigation(cluster_id: str, signature: dict, representative_cases: list[str], affected_areas: list[str]) -> str:
    parts = [f"Start with representative cases {', '.join(representative_cases) or 'none'}"]
    if affected_areas:
        parts.append(f"review affected areas {', '.join(affected_areas)}")
    assertion_type = signature.get("assertion_type")
    if assertion_type:
        parts.append(f"validate the {assertion_type} assertion expectations against actual responses")
    else:
        parts.append("compare expected behavior against actual responses")
    analysis = signature.get("analysis") or {}
    common_root_cause = analysis.get("common_root_cause")
    if common_root_cause:
        parts.append(f"prioritize root cause {common_root_cause}")
    elif analysis.get("root_cause_counts"):
        counts = ", ".join(f"{cause}={count}" for cause, count in analysis["root_cause_counts"].items())
        parts.append(f"compare mixed root causes {counts}")
    return f"{'; '.join(parts)} for {cluster_id}."


def _case_evidence(case_id: str, failures_by_case: dict[str, FailureRecord], cases_by_id: dict[str, EvalCase]) -> CaseEvidence | None:
    failure = failures_by_case.get(case_id)
    if failure is None:
        return None
    case = cases_by_id.get(case_id)
    reasons = [redact_text(reason) or "" for reason in failure.reasons]
    reason = "; ".join(reasons)
    return CaseEvidence(
        case_id=case_id,
        reason=reason,
        reasons=reasons,
        tags=list(case.tags) if case else [],
        priority=case.priority if case else "",
        raw_status=failure.raw_status,
    )


def build_run_analysis(
    run_id: str,
    cases: list[EvalCase],
    raw_results: list[RawResult],
    eval_results: list[EvalResult],
    failures: list[FailureRecord],
    clusters: ClustersFile,
    run_dir: str | None = None,
) -> RunAnalysis:
    """Build the shared run analysis used by human and machine reports."""

    total = len(eval_results)
    passed_case_ids = {result.case_id for result in eval_results if result.passed}
    passed = len(passed_case_ids)
    failed = total - passed
    totals = AnalysisTotals(total=total, passed=passed, failed=failed, pass_rate=_rate(passed, total))

    cases_by_id = {case.id: case for case in cases}
    case_ids = {result.case_id for result in eval_results}
    tag_labels = {case.id: (case.tags or ["untagged"]) for case in cases if case.id in case_ids}
    priority_labels = {case.id: [case.priority or "unprioritized"] for case in cases if case.id in case_ids}
    failures_by_case = {failure.case_id: failure for failure in failures}

    cluster_analyses: list[ClusterAnalysis] = []
    for cluster in clusters.clusters:
        representative_cases = cluster.case_ids[:3]
        evidence = [item for case_id in cluster.case_ids if (item := _case_evidence(case_id, failures_by_case, cases_by_id)) is not None]
        common_signature = cluster.common_signature or {}
        suspected_modules = list(cluster.suspected_modules)
        affected_areas = _affected_areas(common_signature, suspected_modules)
        cluster_analyses.append(
            ClusterAnalysis(
                cluster_id=cluster.cluster_id,
                title=cluster.title,
                severity=cluster.severity,
                cases=cluster.case_ids,
                case_count=len(cluster.case_ids),
                representative_cases=representative_cases,
                common_signature=common_signature,
                signature_explanation=cluster.summary,
                suspected_modules=suspected_modules,
                affected_areas=affected_areas,
                evidence=evidence,
                suggested_investigation=_suggested_investigation(cluster.cluster_id, common_signature, representative_cases, affected_areas),
            )
        )

    return RunAnalysis(
        run_id=run_id,
        run_dir=run_dir or f"runs/{run_id}",
        totals=totals,
        tag_breakdown=_breakdown(tag_labels, passed_case_ids),
        priority_breakdown=_breakdown(priority_labels, passed_case_ids, sort_priority=True),
        clusters=cluster_analyses,
    )
