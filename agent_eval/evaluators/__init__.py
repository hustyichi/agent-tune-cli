from __future__ import annotations

from agent_eval.evaluators.base import decide_pass
from agent_eval.evaluators.execution import ExecutionEvaluator
from agent_eval.evaluators.llm_stub import LlmStubEvaluator
from agent_eval.evaluators.rule import RuleEvaluator
from agent_eval.models import EvalCase, EvalResult, FailureSignature, RawResult


def evaluate_case(run_id: str, case: EvalCase, raw: RawResult, llm_config) -> EvalResult:
    results = []
    results.extend(RuleEvaluator().evaluate(case, raw))
    results.extend(ExecutionEvaluator().evaluate(case, raw))
    results.extend(LlmStubEvaluator(llm_config).evaluate(case, raw))
    passed = raw.status == "success" and decide_pass(results, case.evaluation_policy.pass_rule)
    signature = None if passed else build_signature(case, raw, results)
    return EvalResult(run_id=run_id, case_id=case.id, passed=passed, assertion_results=results, failure_signature=signature)


def build_signature(case: EvalCase, raw: RawResult, results) -> FailureSignature:
    failed = next((r for r in results if not r.passed and not r.skipped), None)
    debug = raw.debug_meta or {}
    first_tool = ""
    if debug.get("tool_calls"):
        first = debug["tool_calls"][0]
        if isinstance(first, dict):
            first_tool = first.get("name", "")
    return FailureSignature(
        assertion_type=(failed.type if failed else raw.status),
        error_code=(debug.get("error_code") or (raw.error.type if raw.error else "assertion_failed")),
        route_name=debug.get("route") or "",
        tool_name=first_tool,
        tag=case.tags[0] if case.tags else "",
        priority=case.priority,
    )
