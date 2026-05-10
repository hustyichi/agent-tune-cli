from __future__ import annotations

from agent_eval.models import EvalCase


def attempt_count_for(case: EvalCase) -> int:
    """Return total independent evaluation attempts for a case."""
    return 1 + max(0, case.evaluation_policy.reruns)


def decide_attempts_pass(passed: list[bool], pass_rule: str) -> bool:
    """Aggregate independent evaluation-attempt outcomes with pass_rule semantics."""
    if not passed:
        return True
    if pass_rule == "any":
        return any(passed)
    if pass_rule == "majority":
        return sum(1 for item in passed if item) > len(passed) / 2
    return all(passed)


def select_representative_attempt(passed: list[bool], aggregate_passed: bool) -> int:
    """Pick the attempt that should represent the aggregate case-level artifact."""
    desired = True if aggregate_passed else False
    for index, item in enumerate(passed):
        if item is desired:
            return index
    return 0
