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

RootCause = tuple[str, str | None, str]

EXECUTION_ROOT_CAUSES = {
    "expected_route": ("route_mismatch", "route"),
    "must_call_tools": ("required_tool_missing", "tool"),
    "forbid_tools": ("forbidden_tool_called", "tool"),
    "max_tool_calls": ("too_many_tool_calls", "tool"),
    "fallback_used": ("fallback_mismatch", "fallback"),
}


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


def _detail(value: str | None) -> str | None:
    if not value:
        return None
    return redact_text(value)


def _root_cause_for_execution_failure(case: EvalCase, raw: RawResult, result) -> RootCause | None:
    if result.type == "min_retrieval_docs":
        expected = case.expected_execution.min_retrieval_docs or 0
        debug = raw.debug_meta or {}
        count = debug.get("retrieval_doc_count") or 0
        retrieval_used = debug.get("retrieval_used")
        cause = "retrieval_missing" if expected > 0 and not retrieval_used and count == 0 else "retrieval_docs_insufficient"
        return cause, _detail(result.reason), "retrieval"
    if result.type in EXECUTION_ROOT_CAUSES:
        cause, phase = EXECUTION_ROOT_CAUSES[result.type]
        return cause, _detail(result.reason), phase
    return None


def _derive_root_cause(case: EvalCase, raw: RawResult, results) -> RootCause:
    if raw.status == "timeout":
        detail = raw.error.message if raw.error else "target execution timed out"
        return "timeout", _detail(detail), "target"
    if raw.status != "success":
        detail = raw.error.message if raw.error else f"raw status is {raw.status}"
        return "target_error", _detail(detail), "target"

    failed_results = [r for r in results if not r.passed and not r.skipped]
    for result in failed_results:
        execution = _root_cause_for_execution_failure(case, raw, result)
        if execution is not None:
            return execution

    for result in failed_results:
        if result.type == "llm_judge":
            return "llm_judge_failure", _detail(result.reason), "judge"

    if failed_results:
        return "content_mismatch", _detail(failed_results[0].reason), "content"
    return "unclassified", None, "unknown"


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
    root_cause, root_cause_detail, execution_phase = _derive_root_cause(case, raw, results)
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
        root_cause=root_cause,
        root_cause_detail=root_cause_detail,
        execution_phase=execution_phase,
        case_tags=list(case.tags),
        debug_flags={
            "retrieval_used": debug.get("retrieval_used"),
            "fallback_used": debug.get("fallback_used"),
            "retrieval_doc_count": debug.get("retrieval_doc_count"),
        },
    )
