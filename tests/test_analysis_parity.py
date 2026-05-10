from __future__ import annotations

import json

from pytest import approx

from agent_eval.analysis import build_run_analysis
from agent_eval.artifacts import build_repair_input
from agent_eval.models import (
    AssertionResult,
    Cluster,
    ClustersFile,
    EvalCase,
    EvalResult,
    FailureRecord,
    FailureSignature,
    RawResult,
)
from agent_eval.reporting import render_summary_from_analysis


def _fixture():
    cases = [
        EvalCase(id="c1", tags=["rag", "pricing"], priority="p1"),
        EvalCase(id="c2", tags=["rag"], priority="p2"),
        EvalCase(id="c3", tags=["smoke"], priority="p3"),
    ]
    raw_results = [
        RawResult(run_id="r1", case_id="c1", status="success", latency_ms=1, response={"answer": "no"}),
        RawResult(run_id="r1", case_id="c2", status="success", latency_ms=1, response={"answer": "still no"}),
        RawResult(run_id="r1", case_id="c3", status="success", latency_ms=1, response={"answer": "ok"}),
    ]
    signature = FailureSignature(
        assertion_type="contains",
        error_code="insufficient_answer",
        route_name="knowledge_qa",
        tool_name="retriever.search",
        tag="rag",
        priority="p1",
        case_tags=["rag", "pricing"],
        metric="correctness",
    )
    eval_results = [
        EvalResult(run_id="r1", case_id="c1", passed=False, assertion_results=[AssertionResult(type="contains", passed=False, reason="Expected answer to contain pricing")], failure_signature=signature),
        EvalResult(run_id="r1", case_id="c2", passed=False, assertion_results=[AssertionResult(type="contains", passed=False, reason="Expected answer to contain discount")], failure_signature=signature),
        EvalResult(run_id="r1", case_id="c3", passed=True),
    ]
    failures = [
        FailureRecord(run_id="r1", case_id="c1", reasons=["Expected answer to contain pricing"], failure_signature=signature, raw_status="success"),
        FailureRecord(run_id="r1", case_id="c2", reasons=["Expected answer to contain discount"], failure_signature=signature, raw_status="success"),
    ]
    clusters = ClustersFile(
        run_id="r1",
        clusters=[
            Cluster(
                cluster_id="cluster_pricing",
                title="Answer content mismatch on knowledge_qa via retriever.search",
                severity="medium",
                case_ids=["c1", "c2"],
                common_signature={
                    "assertion_type": "contains",
                    "error_code": "insufficient_answer",
                    "route_name": "knowledge_qa",
                    "tool_name": "retriever.search",
                    "tag": "rag",
                    "analysis": {"cluster_key_version": "v1", "priority": "p1", "case_tags": ["rag", "pricing"]},
                },
                summary="2 case(s) share a deterministic v1 failure signature; assertion=contains; error=insufficient_answer; route=knowledge_qa; tool=retriever.search.",
                suspected_modules=[],
            )
        ],
    )
    return cases, raw_results, eval_results, failures, clusters


def test_build_run_analysis_computes_shared_run_and_cluster_facts():
    cases, raw_results, eval_results, failures, clusters = _fixture()

    analysis = build_run_analysis("r1", cases, raw_results, eval_results, failures, clusters)

    assert analysis.totals.total == 3
    assert analysis.totals.passed == 1
    assert analysis.totals.failed == 2
    assert analysis.totals.pass_rate == approx(33.3333, rel=1e-4)
    assert {bucket.name: bucket.total for bucket in analysis.tag_breakdown} == {"pricing": 1, "rag": 2, "smoke": 1}
    assert {bucket.name: bucket.failed for bucket in analysis.tag_breakdown}["rag"] == 2
    assert {bucket.name: bucket.total for bucket in analysis.priority_breakdown} == {"p1": 1, "p2": 1, "p3": 1}

    cluster = analysis.clusters[0]
    assert cluster.cluster_id == "cluster_pricing"
    assert cluster.representative_cases == ["c1", "c2"]
    assert cluster.evidence[0].case_id == "c1"
    assert cluster.evidence[0].reason == "Expected answer to contain pricing"
    assert cluster.signature_explanation == clusters.clusters[0].summary
    assert "route:knowledge_qa" in cluster.affected_areas
    assert "tool:retriever.search" in cluster.affected_areas
    assert cluster.suspected_modules == []
    assert "representative cases c1, c2" in cluster.suggested_investigation


def test_markdown_and_repair_json_share_analysis_values():
    cases, raw_results, eval_results, failures, clusters = _fixture()
    analysis = build_run_analysis("r1", cases, raw_results, eval_results, failures, clusters)

    summary = render_summary_from_analysis(analysis)
    repair = build_repair_input("demo", "r1", clusters, failures, analysis=analysis).model_dump(mode="json")

    repair_cluster = repair["clusters"][0]
    assert "## Priority Breakdown" in summary
    assert "## Top Failure Clusters" in summary
    assert "Representative cases: c1, c2" in summary
    assert "Expected answer to contain pricing" in summary
    assert "route:knowledge_qa" in summary
    assert analysis.clusters[0].suggested_investigation in summary

    assert repair["analysis"]["totals"]["failed"] == 2
    assert repair["analysis"]["tag_breakdown"]["rag"]["failed"] == 2
    assert repair["analysis"]["priority_breakdown"]["p1"]["failed"] == 1
    assert repair_cluster["cluster_id"] == "cluster_pricing"
    assert repair_cluster["cases"] == ["c1", "c2"]
    assert repair_cluster["analysis"]["representative_cases"] == ["c1", "c2"]
    assert repair_cluster["analysis"]["signature_explanation"] == analysis.clusters[0].signature_explanation
    assert repair_cluster["analysis"]["suggested_investigation"] == analysis.clusters[0].suggested_investigation
    assert repair_cluster["analysis"]["affected_areas"] == analysis.clusters[0].affected_areas
    assert repair_cluster["evidence"][0]["reason"] == analysis.clusters[0].evidence[0].reason


def test_analysis_evidence_redacts_secret_like_failure_reasons():
    cases, raw_results, eval_results, failures, clusters = _fixture()
    secret = "sk-live-secret-123"
    failures[0] = failures[0].model_copy(update={"reasons": [f"actual token {secret} does not contain safe"]})

    analysis = build_run_analysis("r1", cases, raw_results, eval_results, failures, clusters)
    summary = render_summary_from_analysis(analysis)
    repair = build_repair_input("demo", "r1", clusters, failures, analysis=analysis).model_dump(mode="json")
    legacy_repair = build_repair_input("demo", "r1", clusters, failures).model_dump(mode="json")
    encoded_repair = json.dumps(repair)
    encoded_legacy_repair = json.dumps(legacy_repair)

    assert secret not in analysis.clusters[0].evidence[0].reason
    assert secret not in summary
    assert secret not in encoded_repair
    assert secret not in encoded_legacy_repair
    assert "[REDACTED]" in analysis.clusters[0].evidence[0].reason
    assert "[REDACTED]" in summary
    assert "[REDACTED]" in encoded_repair
    assert "[REDACTED]" in encoded_legacy_repair
