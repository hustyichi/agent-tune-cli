from __future__ import annotations

from typing import Any

from agent_eval.evaluators.base import Evaluator
from agent_eval.models import AssertionResult, EvalCase, RawResult
from agent_eval.utils.jsonpath import get_path


class RuleEvaluator(Evaluator):
    def evaluate(self, case: EvalCase, raw: RawResult) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for assertion in case.assertions:
            typ = assertion.type
            if typ == "llm_judge":
                continue
            if typ == "http_status":
                expected = (
                    assertion.expected
                    if assertion.expected is not None
                    else assertion.value
                )
                actual_status = raw.metadata.get("status_code")
                passed = actual_status == expected
                reason = (
                    f"status_code={actual_status!r}"
                    if passed
                    else f"status_code {actual_status!r} != {expected!r}"
                )
                results.append(AssertionResult(type=typ, passed=passed, reason=reason))
                continue
            if raw.status != "success":
                results.append(
                    AssertionResult(
                        type=typ, passed=False, reason=f"raw status is {raw.status}"
                    )
                )
                continue
            target = assertion.target or "$"
            actual = get_path(raw.response, target, None)
            if typ in {"field_exists", "jsonpath_exists"}:
                passed = actual is not None
                reason = "field exists" if passed else f"missing {target}"
            elif typ == "json_schema_match":
                schema = assertion.schema_spec or {}
                if schema:
                    passed, reason = self._schema_keys(actual, schema)
                else:
                    passed = actual is not None
                    reason = "field exists" if passed else f"missing {target}"
            elif typ == "numeric_threshold":
                passed, reason = self._numeric_threshold(
                    actual,
                    assertion.op,
                    assertion.expected
                    if assertion.expected is not None
                    else assertion.value,
                )
            elif typ in {"contains", "string_contains"}:
                expected = (
                    assertion.contains
                    if assertion.contains is not None
                    else assertion.expected
                )
                passed = (
                    expected in actual
                    if isinstance(actual, (str, list, dict))
                    else False
                )
                reason = (
                    "contains expected value"
                    if passed
                    else f"{actual!r} does not contain {expected!r}"
                )
            elif typ in {"exact_match", "equals"}:
                expected = (
                    assertion.expected
                    if assertion.expected is not None
                    else assertion.value
                )
                passed = actual == expected
                reason = "exact match" if passed else f"{actual!r} != {expected!r}"
            elif typ == "schema_keys":
                schema = assertion.schema_spec or {}
                passed, reason = self._schema_keys(actual, schema)
            else:
                passed = False
                reason = f"unsupported assertion type: {typ}"
            results.append(AssertionResult(type=typ, passed=passed, reason=reason))
        return results

    def _numeric_threshold(
        self, actual: Any, op: str | None, expected: Any
    ) -> tuple[bool, str]:
        if not isinstance(actual, (int, float)) or isinstance(actual, bool):
            return False, f"target is not numeric: {actual!r}"
        if not isinstance(expected, (int, float)) or isinstance(expected, bool):
            return False, f"expected threshold is not numeric: {expected!r}"
        operation = op or "gte"
        checks = {
            "gt": actual > expected,
            "gte": actual >= expected,
            "lt": actual < expected,
            "lte": actual <= expected,
            "eq": actual == expected,
        }
        if operation not in checks:
            return False, f"unsupported numeric op: {operation}"
        passed = checks[operation]
        return (
            passed,
            f"{actual!r} {operation} {expected!r}"
            if passed
            else f"{actual!r} not {operation} {expected!r}",
        )

    def _schema_keys(self, actual: Any, schema: dict[str, Any]) -> tuple[bool, str]:
        if not isinstance(actual, dict):
            return False, "target is not an object"
        for key, expected_type in schema.items():
            if key not in actual:
                return False, f"missing key {key}"
            if expected_type and not self._type_matches(actual[key], expected_type):
                return False, f"key {key} type mismatch"
        return True, "schema keys match"

    def _type_matches(self, value: Any, expected: str) -> bool:
        return {
            "str": isinstance(value, str),
            "string": isinstance(value, str),
            "int": isinstance(value, int) and not isinstance(value, bool),
            "number": isinstance(value, (int, float)) and not isinstance(value, bool),
            "bool": isinstance(value, bool),
            "object": isinstance(value, dict),
            "array": isinstance(value, list),
        }.get(str(expected), True)
