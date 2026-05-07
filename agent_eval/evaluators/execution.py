from __future__ import annotations

from agent_eval.evaluators.base import Evaluator
from agent_eval.models import AssertionResult, EvalCase, RawResult


class ExecutionEvaluator(Evaluator):
    def evaluate(self, case: EvalCase, raw: RawResult) -> list[AssertionResult]:
        exp = case.expected_execution
        results: list[AssertionResult] = []
        debug = raw.debug_meta or {}
        tool_names = [t.get("name") for t in debug.get("tool_calls", []) if isinstance(t, dict)]
        if exp.expected_route is not None:
            actual = debug.get("route")
            results.append(AssertionResult(type="expected_route", passed=actual == exp.expected_route, reason=f"route={actual!r}"))
        for tool in exp.must_call_tools:
            results.append(AssertionResult(type="must_call_tools", passed=tool in tool_names, reason=f"tool {tool} {'called' if tool in tool_names else 'not called'}"))
        for tool in exp.forbid_tools:
            results.append(AssertionResult(type="forbid_tools", passed=tool not in tool_names, reason=f"tool {tool} {'not called' if tool not in tool_names else 'called'}"))
        if exp.max_tool_calls is not None:
            results.append(AssertionResult(type="max_tool_calls", passed=len(tool_names) <= exp.max_tool_calls, reason=f"tool_calls={len(tool_names)}"))
        if exp.min_retrieval_docs is not None:
            count = debug.get("retrieval_doc_count") or 0
            results.append(AssertionResult(type="min_retrieval_docs", passed=count >= exp.min_retrieval_docs, reason=f"retrieval_doc_count={count}"))
        if exp.fallback_used is not None:
            actual = debug.get("fallback_used")
            results.append(AssertionResult(type="fallback_used", passed=actual == exp.fallback_used, reason=f"fallback_used={actual!r}"))
        return results
