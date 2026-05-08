from __future__ import annotations

import hashlib
from collections import defaultdict

from agent_eval.models import Cluster, ClustersFile, EvalResult, FailureRecord, RawResult

CLUSTER_KEY_VERSION = "v1"


def make_failures(run_id: str, eval_results: list[EvalResult], raw_by_case: dict[str, RawResult]) -> list[FailureRecord]:
    failures: list[FailureRecord] = []
    for result in eval_results:
        if result.passed or result.failure_signature is None:
            continue
        reasons = [r.reason for r in result.assertion_results if not r.passed and not r.skipped]
        raw = raw_by_case[result.case_id]
        failures.append(FailureRecord(run_id=run_id, case_id=result.case_id, reasons=reasons, failure_signature=result.failure_signature, raw_status=raw.status))
    return failures


def _title(assertion_type: str, error_code: str, route_name: str, tool_name: str, tag: str) -> str:
    if assertion_type in {"contains", "string_contains", "exact_match", "equals"}:
        base = "Answer content mismatch"
    elif assertion_type in {"expected_route"}:
        base = "Unexpected agent route"
    elif assertion_type in {"must_call_tools"}:
        base = "Required tool was not called"
    elif assertion_type in {"timeout"}:
        base = "Target execution timed out"
    elif assertion_type in {"process", "error"}:
        base = "Target execution failed"
    else:
        base = assertion_type.replace("_", " ").title() if assertion_type else "Unclassified failure"
    if route_name and tool_name:
        return f"{base} on {route_name} via {tool_name}"
    if route_name:
        return f"{base} on {route_name}"
    if tool_name:
        return f"{base} via {tool_name}"
    if tag:
        return f"{base} for {tag} cases"
    if error_code and base == "Unclassified failure":
        return error_code.replace("_", " ").title()
    return base


def _summary(items: list[FailureRecord], common_signature: dict) -> str:
    count = len(items)
    parts = [f"{count} case(s) share a deterministic v1 failure signature"]
    if common_signature.get("assertion_type"):
        parts.append(f"assertion={common_signature['assertion_type']}")
    if common_signature.get("error_code"):
        parts.append(f"error={common_signature['error_code']}")
    if common_signature.get("route_name"):
        parts.append(f"route={common_signature['route_name']}")
    if common_signature.get("tool_name"):
        parts.append(f"tool={common_signature['tool_name']}")
    return "; ".join(parts) + "."


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
        first_sig = items[0].failure_signature
        common_signature = {
            "assertion_type": assertion_type,
            "error_code": error_code,
            "route_name": route_name,
            "tool_name": tool_name,
            "tag": tag,
            "analysis": {
                "cluster_key_version": CLUSTER_KEY_VERSION,
                "display_metric": first_sig.metric,
                "priority": first_sig.priority,
                "case_tags": first_sig.case_tags,
            },
        }
        clusters.append(
            Cluster(
                cluster_id=cluster_id,
                title=_title(assertion_type, error_code, route_name, tool_name, tag),
                case_ids=[i.case_id for i in items],
                common_signature=common_signature,
                summary=_summary(items, common_signature),
                suspected_modules=[],
            )
        )
    return ClustersFile(run_id=run_id, clusters=clusters)
