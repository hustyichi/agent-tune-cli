from __future__ import annotations

from agent_eval.models import AssertionResult, EvalCase, LlmJudgeConfig, RawResult


class LlmStubEvaluator:
    def __init__(self, config: LlmJudgeConfig):
        self.config = config

    def evaluate(self, case: EvalCase, raw: RawResult) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for assertion in case.assertions:
            if assertion.type != "llm_judge":
                continue
            if not self.config.enabled or self.config.provider == "stub":
                if self.config.stub_result == "pass":
                    results.append(AssertionResult(type="llm_judge", metric=assertion.metric, passed=True, score=1.0, reason="stub llm judge pass"))
                elif self.config.stub_result == "fail":
                    results.append(AssertionResult(type="llm_judge", metric=assertion.metric, passed=False, score=0.0, reason="stub llm judge fail"))
                else:
                    results.append(AssertionResult(type="llm_judge", metric=assertion.metric, passed=True, skipped=True, reason="llm judge skipped by offline stub"))
            else:
                results.append(AssertionResult(type="llm_judge", metric=assertion.metric, passed=False, reason="live llm provider not implemented in MVP"))
        return results
