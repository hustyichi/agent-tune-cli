from __future__ import annotations

import json
from pathlib import Path

from agent_eval.artifacts import build_repair_input
from agent_eval.clustering import cluster_failures, make_failures
from agent_eval.config import load_config
from agent_eval.evaluators import evaluate_case
from agent_eval.models import EvalCase, RawResult


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
