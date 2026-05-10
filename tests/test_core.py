from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

import pytest

from agent_eval.clustering import cluster_failures, make_failures
from agent_eval.config import load_config
from agent_eval.dataset import load_cases
from agent_eval.evaluators import evaluate_case
from agent_eval.evaluation_policy import attempt_count_for, decide_attempts_pass, select_representative_attempt
from agent_eval.models import EvalCase, RawResult
from agent_eval.utils.jsonpath import get_path, map_payload
from agent_eval.utils.redact import REDACTED, redact


def test_config_and_dataset_parse(tmp_path: Path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "eval.yaml").write_text(
        """
project:
  name: demo
  mode: script
dataset:
  paths: [cases/sample.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  llm_summary: false
"""
    )
    (tmp_path / "cases" / "sample.jsonl").write_text('{"id":"c1","inputs":{"query":"hello"},"assertions":[]}\n')
    cfg = load_config(tmp_path / "eval.yaml")
    assert cfg.project.name == "demo"
    assert cfg.evaluation.llm_judge.provider == "stub"
    assert cfg.cluster.llm_summary is False
    cases = load_cases(cfg.dataset.paths, tmp_path)
    assert [c.id for c in cases] == ["c1"]


def test_dataset_duplicate_ids_fail(tmp_path: Path):
    p = tmp_path / "cases.jsonl"
    p.write_text('{"id":"dup"}\n{"id":"dup"}\n')
    with pytest.raises(ValueError, match="Duplicate case id"):
        load_cases([str(p)], tmp_path)


def test_jsonpath_subset_and_payload_mapping():
    assert get_path({"answer": {"text": "ok"}}, "$.answer.text") == "ok"
    assert map_payload({"query": "hello"}, {"q": "$.inputs.query", "literal": 3}) == {"q": "hello", "literal": 3}
    with pytest.raises(ValueError):
        map_payload({"query": "hello"}, {"q": "$.context.foo"})


def test_redact_recursive_sensitive_values():
    data = {"Authorization": "Bearer secret", "nested": {"api_key": "abc", "query": "safe"}, "items": [{"password": "pw"}]}
    redacted = redact(data)
    assert redacted["Authorization"] == REDACTED
    assert redacted["nested"]["api_key"] == REDACTED
    assert redacted["items"][0]["password"] == REDACTED
    assert redacted["nested"]["query"] == "safe"


def test_evaluators_pass_and_fail_deterministically():
    case = EvalCase.model_validate(
        {
            "id": "c1",
            "tags": ["rag"],
            "priority": "p1",
            "assertions": [{"type": "contains", "target": "$.answer", "expected": "pricing"}, {"type": "llm_judge", "metric": "correctness"}],
            "expected_execution": {"expected_route": "knowledge_qa", "must_call_tools": ["retriever.search"], "min_retrieval_docs": 1},
        }
    )
    raw = RawResult(
        run_id="r1",
        case_id="c1",
        status="success",
        latency_ms=1,
        request={},
        response={"answer": "pricing details"},
        debug_meta={"route": "knowledge_qa", "retrieval_doc_count": 1, "tool_calls": [{"name": "retriever.search"}]},
    )
    llm_cfg = load_config(Path("does-not-exist.yaml")).evaluation.llm_judge
    result = evaluate_case("r1", case, raw, llm_cfg)
    assert result.passed is True
    assert any(r.type == "llm_judge" and r.skipped for r in result.assertion_results)

    bad_raw = raw.model_copy(update={"response": {"answer": "other"}, "debug_meta": {"route": "fallback", "tool_calls": []}})
    bad = evaluate_case("r1", case, bad_raw, llm_cfg)
    assert bad.passed is False
    assert bad.failure_signature is not None
    assert bad.failure_signature.assertion_type == "contains"


def test_evaluation_policy_attempt_helpers():
    default_case = EvalCase.model_validate({"id": "default"})
    rerun_case = EvalCase.model_validate({"id": "rerun", "evaluation_policy": {"reruns": 2}})

    assert attempt_count_for(default_case) == 1
    assert attempt_count_for(rerun_case) == 3

    assert decide_attempts_pass([True, True], "all") is True
    assert decide_attempts_pass([True, False], "all") is False
    assert decide_attempts_pass([False, True], "any") is True
    assert decide_attempts_pass([False, False], "any") is False
    assert decide_attempts_pass([True, False, True], "majority") is True
    assert decide_attempts_pass([True, False, False], "majority") is False

    assert select_representative_attempt([False, True], aggregate_passed=True) == 1
    assert select_representative_attempt([True, False], aggregate_passed=False) == 1


def test_clustering_stable_ids():
    cfg = load_config(Path("does-not-exist.yaml"))
    case = EvalCase.model_validate({"id": "c1", "tags": ["smoke"], "priority": "p2", "assertions": [{"type": "contains", "target": "$.answer", "expected": "x"}]})
    raw = RawResult(run_id="r1", case_id="c1", status="success", latency_ms=1, request={}, response={"answer": "no"}, debug_meta={"error_code": "insufficient_answer"})
    ev = evaluate_case("r1", case, raw, cfg.evaluation.llm_judge)
    failures = make_failures("r1", [ev], {"c1": raw})
    first = cluster_failures("r1", failures)
    second = cluster_failures("r1", failures)
    assert first.clusters[0].cluster_id == second.clusters[0].cluster_id
    assert first.clusters[0].case_ids == ["c1"]

from agent_eval.run_id import new_run_id
from agent_eval.runners.script import ScriptRunner


def test_run_id_rejects_path_traversal():
    with pytest.raises(ValueError):
        new_run_id("../outside")
    assert new_run_id("safe-run_1.2") == "safe-run_1.2"


def test_script_runner_redacts_stderr_and_handles_failures(tmp_path: Path):
    script = tmp_path / "bad.py"
    script.write_text("import sys; sys.stderr.write('SENTINEL_SECRET_TOKEN'); sys.exit(2)")
    case = EvalCase.model_validate({"id": "bad", "inputs": {"api_key": "SENTINEL_API_KEY"}})
    result = ScriptRunner(f"{sys.executable} {script} --input-file {{input_file}}", tmp_path, 5).run_once(case, "r1")
    dumped = result.model_dump(mode="json")
    assert result.status == "error"
    assert "SENTINEL_SECRET_TOKEN" not in json.dumps(dumped)
    assert "SENTINEL_API_KEY" not in json.dumps(dumped)
    assert "[REDACTED]" in json.dumps(dumped)


def test_script_runner_invalid_json_timeout_and_retry(tmp_path: Path):
    invalid = tmp_path / "invalid.py"
    invalid.write_text("print('not-json')")
    case = EvalCase.model_validate({"id": "invalid"})
    invalid_result = ScriptRunner(f"{sys.executable} {invalid} --input-file {{input_file}}", tmp_path, 5).run_once(case, "r1")
    assert invalid_result.status == "error"
    assert invalid_result.error and invalid_result.error.type == "parse"

    slow = tmp_path / "slow.py"
    slow.write_text("import time; time.sleep(2)")
    timeout_result = ScriptRunner(f"{sys.executable} {slow} --input-file {{input_file}}", tmp_path, 0.1).run_once(case, "r1")
    assert timeout_result.status == "timeout"

    counter = tmp_path / "counter.txt"
    flaky = tmp_path / "flaky.py"
    flaky.write_text(
        """
import json, pathlib, sys
counter = pathlib.Path('counter.txt')
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
if n == 0:
    sys.exit(1)
print(json.dumps({'answer': 'ok'}))
""".strip()
    )
    retry_result = ScriptRunner(f"{sys.executable} {flaky} --input-file {{input_file}}", tmp_path, 5).run_with_retries(case, "r1", 1)
    assert retry_result.status == "success"
    assert retry_result.attempt_count == 2

from agent_eval.artifacts import resolve_run


def test_resolve_run_rejects_traversal(tmp_path: Path):
    (tmp_path / "runs").mkdir()
    with pytest.raises(ValueError):
        resolve_run(tmp_path, "../outside")

from agent_eval.utils.redact import redact_text
from agent_eval.runners.http import HttpRunner
from agent_eval.models import HttpTargetConfig


def test_redact_text_masks_flag_values_and_key_shaped_tokens():
    text = "python sample_agent.py --api-key sk-live-abc123 --token token-secret-456 Bearer api-secret-789"
    redacted = redact_text(text)
    assert "sk-live-abc123" not in redacted
    assert "token-secret-456" not in redacted
    assert "api-secret-789" not in redacted
    assert redacted.count("[REDACTED]") >= 3


def test_http_timeout_and_retry(monkeypatch, tmp_path: Path):
    calls = {"n": 0}

    def fake_request(*args, **kwargs):
        import httpx
        calls["n"] += 1
        raise httpx.TimeoutException("timeout with sk-live-abc123")

    monkeypatch.setattr("agent_eval.runners.http.httpx.request", fake_request)
    runner = HttpRunner(HttpTargetConfig(url="http://example.invalid", payload_mapping={"query": "$.inputs.query"}), tmp_path, 0.1)
    case = EvalCase.model_validate({"id": "h-timeout", "inputs": {"query": "hello", "api_key": "sk-live-abc123"}})
    result = runner.run_with_retries(case, "r1", 1)
    dumped = json.dumps(result.model_dump(mode="json"))
    assert calls["n"] == 2
    assert result.status == "timeout"
    assert result.attempt_count == 2
    assert "sk-live-abc123" not in dumped
    assert "[REDACTED]" in dumped

from agent_eval.models import LlmJudgeConfig


def test_llm_judge_deepeval_provider_uses_mapping_and_redacts_reason(monkeypatch):
    import types

    calls = {}

    class FakeTestCase:
        def __init__(self, *, input, actual_output):  # noqa: A002 - match DeepEval API
            calls["test_case"] = {"input": input, "actual_output": actual_output}

    class FakeMetric:
        def __init__(self, *, threshold, model, include_reason):
            calls["metric"] = {"threshold": threshold, "model": model, "include_reason": include_reason}
            self.score = 0.82
            self.reason = "looks relevant but saw sk-live-secret-123"

        def measure(self, test_case):
            calls["measured"] = test_case

    deepeval_mod = types.ModuleType("deepeval")
    metrics_mod = types.ModuleType("deepeval.metrics")
    metrics_mod.AnswerRelevancyMetric = FakeMetric
    test_case_mod = types.ModuleType("deepeval.test_case")
    test_case_mod.LLMTestCase = FakeTestCase
    monkeypatch.setitem(sys.modules, "deepeval", deepeval_mod)
    monkeypatch.setitem(sys.modules, "deepeval.metrics", metrics_mod)
    monkeypatch.setitem(sys.modules, "deepeval.test_case", test_case_mod)

    case = EvalCase.model_validate({"id": "llm", "inputs": {"query": "pricing?"}, "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": "pricing is available"})
    cfg = LlmJudgeConfig.model_validate({"enabled": True, "provider": "deepeval", "model": "gpt-test", "threshold": 0.7})

    result = evaluate_case("r1", case, raw, cfg)
    llm = next(r for r in result.assertion_results if r.type == "llm_judge")

    assert result.passed is True
    assert llm.score == 0.82
    assert "sk-live-secret-123" not in llm.reason
    assert "[REDACTED]" in llm.reason
    assert calls["test_case"] == {"input": "pricing?", "actual_output": "pricing is available"}
    assert calls["metric"] == {"threshold": 0.7, "model": "gpt-test", "include_reason": True}
    assert "measured" in calls


def test_llm_judge_disabled_deepeval_provider_does_not_import(monkeypatch):
    def fail_import(name, *args, **kwargs):
        if name.startswith("deepeval"):
            raise AssertionError("deepeval should not be imported when llm_judge is disabled")
        return importlib.import_module(name, *args, **kwargs)

    monkeypatch.setattr("agent_eval.evaluators.llm_judge.importlib.import_module", fail_import)
    case = EvalCase.model_validate({"id": "llm", "inputs": {"query": "pricing?"}, "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": "pricing is available"})
    cfg = LlmJudgeConfig.model_validate({"enabled": False, "provider": "deepeval", "model": "gpt-test"})

    result = evaluate_case("r1", case, raw, cfg)
    llm = next(r for r in result.assertion_results if r.type == "llm_judge")

    assert result.passed is True
    assert llm.skipped is True


def test_llm_judge_deepeval_missing_dependency_is_failed_assertion(monkeypatch):
    def missing_import(name, *args, **kwargs):
        if name.startswith("deepeval"):
            raise ModuleNotFoundError("No module named 'deepeval'", name="deepeval")
        return importlib.import_module(name, *args, **kwargs)

    monkeypatch.setattr("agent_eval.evaluators.llm_judge.importlib.import_module", missing_import)
    case = EvalCase.model_validate({"id": "llm", "inputs": {"query": "pricing?"}, "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": "pricing is available"})
    cfg = LlmJudgeConfig.model_validate({"enabled": True, "provider": "deepeval", "model": "gpt-test"})

    result = evaluate_case("r1", case, raw, cfg)
    llm = next(r for r in result.assertion_results if r.type == "llm_judge")

    assert result.passed is False
    assert llm.passed is False
    assert "deepeval" in llm.reason.lower()
    assert "not implemented" not in llm.reason.lower()


def test_llm_judge_unsupported_metric_fails_clearly():
    case = EvalCase.model_validate({"id": "llm", "inputs": {"query": "pricing?"}, "assertions": [{"type": "llm_judge", "metric": "faithfulness"}]})
    raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": "pricing is available"})
    cfg = LlmJudgeConfig.model_validate({"enabled": True, "provider": "deepeval", "model": "gpt-test"})

    result = evaluate_case("r1", case, raw, cfg)
    llm = next(r for r in result.assertion_results if r.type == "llm_judge")

    assert result.passed is False
    assert "unsupported llm_judge metric" in llm.reason


def test_rule_evaluator_http_status_numeric_and_schema_subset():
    cfg = load_config(Path("does-not-exist.yaml"))
    raw = RawResult(
        run_id="r1",
        case_id="rules",
        status="success",
        latency_ms=1,
        request={},
        response={"answer": "ok", "score": 0.91},
        metadata={"status_code": 200},
    )
    passing = EvalCase.model_validate(
        {
            "id": "rules",
            "assertions": [
                {"type": "http_status", "expected": 200},
                {"type": "numeric_threshold", "target": "$.score", "op": "gte", "expected": 0.9},
                {"type": "json_schema_match", "target": "$", "schema": {"answer": "string", "score": "number"}},
            ],
        }
    )
    passed = evaluate_case("r1", passing, raw, cfg.evaluation.llm_judge)
    assert passed.passed is True

    failing = EvalCase.model_validate(
        {
            "id": "rules",
            "assertions": [
                {"type": "http_status", "expected": 201},
                {"type": "numeric_threshold", "target": "$.score", "op": "lt", "expected": 0.9},
                {"type": "json_schema_match", "target": "$", "schema": {"answer": "string", "score": "string"}},
            ],
        }
    )
    failed = evaluate_case("r1", failing, raw, cfg.evaluation.llm_judge)
    assert failed.passed is False
    assert {r.type for r in failed.assertion_results if not r.passed} == {"http_status", "numeric_threshold", "json_schema_match"}


def test_llm_judge_deepeval_mapping_preserves_falsy_and_uses_redacted_json_fallback(monkeypatch):
    import types

    calls = []

    class FakeTestCase:
        def __init__(self, *, input, actual_output):  # noqa: A002 - match DeepEval API
            calls.append({"input": input, "actual_output": actual_output})

    class FakeMetric:
        def __init__(self, *, threshold, model, include_reason):
            self.score = 1.0
            self.reason = "ok"

        def measure(self, test_case):
            return None

    metrics_mod = types.ModuleType("deepeval.metrics")
    metrics_mod.AnswerRelevancyMetric = FakeMetric
    test_case_mod = types.ModuleType("deepeval.test_case")
    test_case_mod.LLMTestCase = FakeTestCase
    monkeypatch.setitem(sys.modules, "deepeval", types.ModuleType("deepeval"))
    monkeypatch.setitem(sys.modules, "deepeval.metrics", metrics_mod)
    monkeypatch.setitem(sys.modules, "deepeval.test_case", test_case_mod)

    cfg = LlmJudgeConfig.model_validate({"enabled": True, "provider": "deepeval", "model": "gpt-test"})
    assertion_case = {"id": "llm", "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]}

    for value in (0, False):
        case = EvalCase.model_validate({**assertion_case, "inputs": {"query": "q"}})
        raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": value})
        result = evaluate_case("r1", case, raw, cfg)
        assert result.passed is True

    fallback_case = EvalCase.model_validate({**assertion_case, "inputs": {"api_key": "sk-live-secret-123", "topic": "pricing"}})
    fallback_raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"token": "sk-live-secret-456", "result": "ok"})
    result = evaluate_case("r1", fallback_case, fallback_raw, cfg)
    assert result.passed is True

    assert calls[0]["actual_output"] == "0"
    assert calls[1]["actual_output"] == "False"
    assert "sk-live-secret" not in calls[2]["input"]
    assert "sk-live-secret" not in calls[2]["actual_output"]
    assert "[REDACTED]" in calls[2]["input"]
    assert "[REDACTED]" in calls[2]["actual_output"]


def test_llm_judge_deepeval_empty_mapping_and_provider_exception_are_safe(monkeypatch):
    import types

    class RaisingTestCase:
        def __init__(self, *, input, actual_output):  # noqa: A002 - match DeepEval API
            pass

    class RaisingMetric:
        def __init__(self, *, threshold, model, include_reason):
            pass

        def measure(self, test_case):
            raise RuntimeError("provider leaked sk-live-secret-789")

    metrics_mod = types.ModuleType("deepeval.metrics")
    metrics_mod.AnswerRelevancyMetric = RaisingMetric
    test_case_mod = types.ModuleType("deepeval.test_case")
    test_case_mod.LLMTestCase = RaisingTestCase
    monkeypatch.setitem(sys.modules, "deepeval", types.ModuleType("deepeval"))
    monkeypatch.setitem(sys.modules, "deepeval.metrics", metrics_mod)
    monkeypatch.setitem(sys.modules, "deepeval.test_case", test_case_mod)

    cfg = LlmJudgeConfig.model_validate({"enabled": True, "provider": "deepeval", "model": "gpt-test"})
    empty_case = EvalCase.model_validate({"id": "llm", "inputs": {"query": ""}, "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": "ok"})
    empty = evaluate_case("r1", empty_case, raw, cfg)
    assert empty.passed is False
    assert "input is empty" in empty.assertion_results[0].reason

    empty_output_case = EvalCase.model_validate({"id": "llm", "inputs": {"query": "pricing"}, "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    empty_output_raw = RawResult(run_id="r1", case_id="llm", status="success", latency_ms=1, request={}, response={"answer": ""})
    empty_output = evaluate_case("r1", empty_output_case, empty_output_raw, cfg)
    assert empty_output.passed is False
    assert "actual_output is empty" in empty_output.assertion_results[0].reason

    case = EvalCase.model_validate({"id": "llm", "inputs": {"query": "pricing"}, "assertions": [{"type": "llm_judge", "metric": "answer_relevancy"}]})
    provider_error = evaluate_case("r1", case, raw, cfg)
    llm = provider_error.assertion_results[0]
    assert provider_error.passed is False
    assert "sk-live-secret-789" not in llm.reason
    assert "[REDACTED]" in llm.reason
