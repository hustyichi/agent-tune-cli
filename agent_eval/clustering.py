from __future__ import annotations

import hashlib
from collections import defaultdict

from agent_eval.models import Cluster, ClustersFile, EvalResult, FailureRecord, RawResult


def make_failures(run_id: str, eval_results: list[EvalResult], raw_by_case: dict[str, RawResult]) -> list[FailureRecord]:
    failures: list[FailureRecord] = []
    for result in eval_results:
        if result.passed or result.failure_signature is None:
            continue
        reasons = [r.reason for r in result.assertion_results if not r.passed and not r.skipped]
        raw = raw_by_case[result.case_id]
        failures.append(FailureRecord(run_id=run_id, case_id=result.case_id, reasons=reasons, failure_signature=result.failure_signature, raw_status=raw.status))
    return failures


def cluster_failures(run_id: str, failures: list[FailureRecord]) -> ClustersFile:
    groups: dict[tuple[str, str, str, str, str], list[FailureRecord]] = defaultdict(list)
    for failure in failures:
        sig = failure.failure_signature
        key = (sig.assertion_type, sig.error_code, sig.route_name, sig.tool_name, sig.tag)
        groups[key].append(failure)
    clusters: list[Cluster] = []
    for key, items in sorted(groups.items(), key=lambda kv: kv[0]):
        assertion_type, error_code, route_name, tool_name, tag = key
        digest = hashlib.sha1("|".join(key).encode()).hexdigest()[:8]
        cluster_id = f"cluster_{digest}"
        title_parts = [p for p in [assertion_type, error_code, route_name or tag] if p]
        title = " / ".join(title_parts) if title_parts else "Unclassified failure"
        common_signature = {
            "assertion_type": assertion_type,
            "error_code": error_code,
            "route_name": route_name,
            "tool_name": tool_name,
            "tag": tag,
        }
        summary = f"{len(items)} case(s) share failure signature {common_signature}."
        clusters.append(Cluster(cluster_id=cluster_id, title=title, case_ids=[i.case_id for i in items], common_signature=common_signature, summary=summary))
    return ClustersFile(run_id=run_id, clusters=clusters)
