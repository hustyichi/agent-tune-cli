from __future__ import annotations

from agent_eval.models import AssertionResult, EvalCase, RawResult


def decide_pass(results: list[AssertionResult], pass_rule: str) -> bool:
    considered = [r for r in results if not r.skipped]
    if not considered:
        return True
    if pass_rule == "any":
        return any(r.passed for r in considered)
    if pass_rule == "majority":
        return sum(1 for r in considered if r.passed) > len(considered) / 2
    return all(r.passed for r in considered)


class Evaluator:
    def evaluate(self, case: EvalCase, raw: RawResult) -> list[AssertionResult]:
        raise NotImplementedError
