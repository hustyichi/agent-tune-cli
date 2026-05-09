from __future__ import annotations

import json
from typing import Any

from agent_eval.evaluators.base import decide_pass
from agent_eval.evaluators.execution import ExecutionEvaluator
from agent_eval.evaluators.llm_judge import LlmJudgeEvaluator
from agent_eval.evaluators.rule import RuleEvaluator
from agent_eval.models import EvalCase, EvalResult, FailureSignature, RawResult
from agent_eval.utils.jsonpath import get_path
from agent_eval.utils.redact import redact, redact_text


def evaluate_case(run_id: str, case: EvalCase, raw: RawResult, llm_config) -> EvalResult:
    results = []
    results.extend(RuleEvaluator().evaluate(case, raw))
    results.extend(ExecutionEvaluator().evaluate(case, raw))
    results.extend(LlmJudgeEvaluator(llm_config).evaluate(case, raw))
    passed = raw.status == "success" and decide_pass(results, case.evaluation_policy.pass_rule)
    signature = None if passed else build_signature(case, raw, results)
    return EvalResult(run_id=run_id, case_id=case.id, passed=passed, assertion_results=results, failure_signature=signature)


def _summary(value: Any, limit: int = 160) -> str:
    redacted = redact(value)
    try:
        text = json.dumps(redacted, ensure_ascii=False, sort_keys=True)
    except TypeError:
        text = str(redacted)
    text = redact_text(text) or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _matching_assertion(case: EvalCase, typ: str):
    aliases = {
        "expected_route": "expected_execution",
        "must_call_tools": "expected_execution",
        "forbid_tools": "expected_execution",
        "max_tool_calls": "expected_execution",
        "min_retrieval_docs": "expected_execution",
        "fallback_used": "expected_execution",
    }
    if typ in aliases:
        return None
    return next((assertion for assertion in case.assertions if assertion.type == typ), None)


def build_signature(case: EvalCase, raw: RawResult, results) -> FailureSignature:
    failed = next((r for r in results if not r.passed and not r.skipped), None)
    debug = raw.debug_meta or {}
    first_tool = ""
    if debug.get("tool_calls"):
        first = debug["tool_calls"][0]
        if isinstance(first, dict):
            first_tool = first.get("name", "")
    typ = failed.type if failed else raw.status
    assertion = _matching_assertion(case, typ)
    expected = None
    actual = None
    metric = failed.metric if failed else None
    if assertion is not None:
        expected = assertion.expected if assertion.expected is not None else assertion.value
        if expected is None and assertion.contains is not None:
            expected = assertion.contains
        metric = metric or assertion.metric
        actual = get_path(raw.response, assertion.target or "$", None)
    return FailureSignature(
        assertion_type=typ,
        error_code=(debug.get("error_code") or (raw.error.type if raw.error else "assertion_failed")),
        route_name=debug.get("route") or "",
        tool_name=first_tool,
        tag=case.tags[0] if case.tags else "",
        priority=case.priority,
        metric=metric,
        assertion_reason_code=(redact_text(failed.reason.split(":", 1)[0]) if failed and failed.reason else None),
        expected_summary=_summary(expected) if expected is not None else None,
        actual_summary=_summary(actual) if actual is not None else None,
        case_tags=list(case.tags),
        debug_flags={
            "retrieval_used": debug.get("retrieval_used"),
            "fallback_used": debug.get("fallback_used"),
            "retrieval_doc_count": debug.get("retrieval_doc_count"),
        },
    )
