from __future__ import annotations

import json
from pathlib import Path

from agent_eval.analysis import build_run_analysis
from agent_eval.artifacts import build_repair_input
from agent_eval.clustering import CLUSTER_KEY_VERSION, cluster_failures, make_failures
from agent_eval.config import load_config
from agent_eval.evaluators import evaluate_case
from agent_eval.models import ErrorInfo, EvalCase, FailureRecord, FailureSignature, LlmJudgeConfig, RawResult
from agent_eval.reporting import render_summary_from_analysis


def test_failure_signature_adds_optional_redacted_analysis_fields():
    case = EvalCase.model_validate(
        {
            "id": "secret_case",
            "tags": ["rag", "secret"],
            "priority": "p1",
            "assertions": [
                {
                    "type": "contains",
                    "target": "$.answer",
                    "expected": "safe",
                    "metric": "correctness",
                }
            ],
        }
    )
    raw = RawResult(
        run_id="r1",
        case_id="secret_case",
        status="success",
        latency_ms=1,
        request={},
        response={"answer": "token sk-live-secret-123 was exposed"},
        debug_meta={"route": "knowledge_qa", "error_code": "insufficient_answer", "tool_calls": [{"name": "retriever.search"}]},
    )

    result = evaluate_case("r1", case, raw, load_config(Path("does-not-exist.yaml")).evaluation.llm_judge)
    sig = result.failure_signature
    assert sig is not None
    assert sig.assertion_type == "contains"
    assert sig.error_code == "insufficient_answer"
    assert sig.route_name == "knowledge_qa"
    assert sig.tool_name == "retriever.search"
    assert sig.tag == "rag"
    assert sig.priority == "p1"
    dumped = sig.model_dump(mode="json")
    assert dumped["metric"] == "correctness"
    assert dumped["case_tags"] == ["rag", "secret"]
    encoded = json.dumps(dumped)
    assert "sk-live-secret-123" not in encoded
    assert "[REDACTED]" in encoded


def test_cluster_naming_is_deterministic_and_preserves_identity_key():
    cfg = load_config(Path("does-not-exist.yaml"))
    case = EvalCase.model_validate(
        {
            "id": "c1",
            "tags": ["rag"],
            "priority": "p2",
            "assertions": [{"type": "contains", "target": "$.answer", "expected": "pricing"}],
        }
    )
    raw = RawResult(
        run_id="r1",
        case_id="c1",
        status="success",
        latency_ms=1,
        request={},
        response={"answer": "other"},
        debug_meta={"route": "knowledge_qa", "error_code": "insufficient_answer", "tool_calls": [{"name": "retriever.search"}]},
    )
    ev = evaluate_case("r1", case, raw, cfg.evaluation.llm_judge)
    failures = make_failures("r1", [ev], {"c1": raw})

    first = cluster_failures("r1", failures).clusters[0]
    second = cluster_failures("r1", failures).clusters[0]

    assert first.cluster_id == second.cluster_id
    assert first.title == "Answer content mismatch on knowledge_qa via retriever.search"
    assert "insufficient_answer" in first.summary
    assert first.common_signature["assertion_type"] == "contains"
    assert first.common_signature["route_name"] == "knowledge_qa"
    assert first.common_signature["analysis"]["cluster_key_version"] == "v1"
    assert first.suspected_modules == []


def test_repair_input_preserves_legacy_fields_and_adds_namespaced_analysis():
    cfg = load_config(Path("does-not-exist.yaml"))
    case = EvalCase.model_validate({"id": "c1", "assertions": [{"type": "contains", "target": "$.answer", "expected": "x"}]})
    raw = RawResult(run_id="r1", case_id="c1", status="success", latency_ms=1, request={}, response={"answer": "no"}, debug_meta={"error_code": "insufficient_answer"})
    ev = evaluate_case("r1", case, raw, cfg.evaluation.llm_judge)
    failures = make_failures("r1", [ev], {"c1": raw})
    clusters = cluster_failures("r1", failures)

    repair = build_repair_input("demo", "r1", clusters, failures).model_dump(mode="json")

    cluster = repair["clusters"][0]
    assert cluster["cluster_id"]
    assert cluster["cases"] == ["c1"]
    assert cluster["common_signature"]
    assert cluster["evidence"]
    assert cluster["analysis"]["signature_explanation"]
    assert cluster["analysis"]["representative_cases"] == ["c1"]


def test_root_cause_prefers_execution_failure_over_earlier_content_failure():
    cfg = load_config(Path("does-not-exist.yaml"))
    case = EvalCase.model_validate(
        {
            "id": "masked_rag_failure",
            "assertions": [{"type": "contains", "target": "$.answer", "expected": "pricing"}],
            "expected_execution": {"must_call_tools": ["retriever.search"]},
        }
    )
    raw = RawResult(
        run_id="r1",
        case_id="masked_rag_failure",
        status="success",
        latency_ms=1,
        request={},
        response={"answer": "no relevant answer"},
        debug_meta={"route": "knowledge_qa", "tool_calls": []},
    )

    result = evaluate_case("r1", case, raw, cfg.evaluation.llm_judge)

    assert [r.type for r in result.assertion_results if not r.passed] == ["contains", "must_call_tools"]
    assert result.failure_signature is not None
    assert result.failure_signature.assertion_type == "contains"
    assert result.failure_signature.root_cause == "required_tool_missing"
    assert result.failure_signature.execution_phase == "tool"


def test_root_cause_distinguishes_retrieval_missing_and_insufficient_docs():
    cfg = load_config(Path("does-not-exist.yaml"))
    case = EvalCase.model_validate({"id": "retrieval", "expected_execution": {"min_retrieval_docs": 2}})
    missing_raw = RawResult(
        run_id="r1",
        case_id="retrieval_missing",
        status="success",
        latency_ms=1,
        request={},
        response={},
        debug_meta={"retrieval_used": False, "retrieval_doc_count": 0},
    )
    insufficient_raw = missing_raw.model_copy(
        update={
            "case_id": "retrieval_insufficient",
            "debug_meta": {"retrieval_used": True, "retrieval_doc_count": 1},
        }
    )

    missing = evaluate_case("r1", case.model_copy(update={"id": "retrieval_missing"}), missing_raw, cfg.evaluation.llm_judge)
    insufficient = evaluate_case("r1", case.model_copy(update={"id": "retrieval_insufficient"}), insufficient_raw, cfg.evaluation.llm_judge)

    assert missing.failure_signature is not None
    assert missing.failure_signature.root_cause == "retrieval_missing"
    assert missing.failure_signature.execution_phase == "retrieval"
    assert insufficient.failure_signature is not None
    assert insufficient.failure_signature.root_cause == "retrieval_docs_insufficient"
    assert insufficient.failure_signature.execution_phase == "retrieval"


def test_root_cause_llm_judge_failure_when_no_higher_precedence_failure():
    case = EvalCase.model_validate({"id": "judge", "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    raw = RawResult(run_id="r1", case_id="judge", status="success", latency_ms=1, request={}, response={"answer": "ok"}, debug_meta={})

    result = evaluate_case("r1", case, raw, LlmJudgeConfig(enabled=True, provider="stub", model="stub", stub_result="fail"))

    assert result.failure_signature is not None
    assert result.failure_signature.root_cause == "llm_judge_failure"
    assert result.failure_signature.execution_phase == "judge"


def test_root_cause_raw_status_precedence_and_redacted_detail():
    cfg = load_config(Path("does-not-exist.yaml"))
    case = EvalCase.model_validate({"id": "target_error"})
    raw = RawResult(
        run_id="r1",
        case_id="target_error",
        status="error",
        latency_ms=1,
        request={},
        response={},
        debug_meta={},
        error=ErrorInfo(message="backend leaked sk-live-secret-123", type="process"),
    )

    result = evaluate_case("r1", case, raw, cfg.evaluation.llm_judge)

    assert result.failure_signature is not None
    assert result.failure_signature.root_cause == "target_error"
    assert result.failure_signature.execution_phase == "target"
    assert "sk-live-secret-123" not in (result.failure_signature.root_cause_detail or "")
    assert "[REDACTED]" in (result.failure_signature.root_cause_detail or "")

    timeout = raw.model_copy(update={"case_id": "timeout", "status": "timeout", "error": ErrorInfo(message="timed out", type="timeout")})
    timeout_result = evaluate_case("r1", case.model_copy(update={"id": "timeout"}), timeout, cfg.evaluation.llm_judge)

    assert timeout_result.failure_signature is not None
    assert timeout_result.failure_signature.root_cause == "timeout"


def test_cluster_root_cause_aggregation_preserves_v1_identity_for_mixed_causes():
    assert CLUSTER_KEY_VERSION == "v1"
    failures = [
        FailureRecord(
            run_id="r1",
            case_id="c1",
            reasons=["tool retriever.search not called"],
            raw_status="success",
            failure_signature=FailureSignature(
                assertion_type="contains",
                error_code="assertion_failed",
                route_name="knowledge_qa",
                tool_name="",
                tag="rag",
                root_cause="required_tool_missing",
            ),
        ),
        FailureRecord(
            run_id="r1",
            case_id="c2",
            reasons=["retrieval_doc_count=0"],
            raw_status="success",
            failure_signature=FailureSignature(
                assertion_type="contains",
                error_code="assertion_failed",
                route_name="knowledge_qa",
                tool_name="",
                tag="rag",
                root_cause="retrieval_missing",
            ),
        ),
    ]

    clusters = cluster_failures("r1", failures)

    assert len(clusters.clusters) == 1
    cluster = clusters.clusters[0]
    analysis = cluster.common_signature["analysis"]
    assert analysis["cluster_key_version"] == "v1"
    assert analysis["root_causes"] == ["required_tool_missing", "retrieval_missing"]
    assert analysis["root_cause_counts"] == {"required_tool_missing": 1, "retrieval_missing": 1}
    assert analysis["common_root_cause"] is None


def test_homogeneous_root_cause_reaches_clusters_repair_and_summary():
    cfg = load_config(Path("does-not-exist.yaml"))
    cases = [
        EvalCase.model_validate(
            {
                "id": "c1",
                "tags": ["rag"],
                "assertions": [{"type": "contains", "target": "$.answer", "expected": "pricing"}],
                "expected_execution": {"must_call_tools": ["retriever.search"]},
            }
        ),
        EvalCase.model_validate(
            {
                "id": "c2",
                "tags": ["rag"],
                "assertions": [{"type": "contains", "target": "$.answer", "expected": "discount"}],
                "expected_execution": {"must_call_tools": ["retriever.search"]},
            }
        ),
    ]
    raws = [
        RawResult(run_id="r1", case_id="c1", status="success", latency_ms=1, request={}, response={"answer": "no"}, debug_meta={"route": "knowledge_qa", "tool_calls": []}),
        RawResult(run_id="r1", case_id="c2", status="success", latency_ms=1, request={}, response={"answer": "no"}, debug_meta={"route": "knowledge_qa", "tool_calls": []}),
    ]
    evals = [evaluate_case("r1", case, raw, cfg.evaluation.llm_judge) for case, raw in zip(cases, raws)]
    failures = make_failures("r1", evals, {raw.case_id: raw for raw in raws})
    clusters = cluster_failures("r1", failures)

    cluster_analysis = clusters.clusters[0].common_signature["analysis"]
    assert cluster_analysis["root_causes"] == ["required_tool_missing"]
    assert cluster_analysis["root_cause_counts"] == {"required_tool_missing": 2}
    assert cluster_analysis["common_root_cause"] == "required_tool_missing"

    analysis = build_run_analysis("r1", cases, raws, evals, failures, clusters)
    summary = render_summary_from_analysis(analysis)
    repair = build_repair_input("demo", "r1", clusters, failures, analysis=analysis).model_dump(mode="json")

    assert "Root cause: required_tool_missing" in summary
    assert repair["clusters"][0]["analysis"]["root_causes"] == ["required_tool_missing"]
    assert repair["clusters"][0]["analysis"]["root_cause_counts"] == {"required_tool_missing": 2}
    assert repair["clusters"][0]["analysis"]["common_root_cause"] == "required_tool_missing"
