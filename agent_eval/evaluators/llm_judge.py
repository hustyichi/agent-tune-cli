from __future__ import annotations

import importlib
import json
from typing import Any, Protocol

from agent_eval.models import (
    AssertionResult,
    AssertionSpec,
    EvalCase,
    LlmJudgeConfig,
    RawResult,
)
from agent_eval.utils.redact import redact, redact_text

SUPPORTED_DEEPEVAL_METRICS = {"answer_relevancy"}
REASON_LIMIT = 500


class LlmJudgeProvider(Protocol):
    def evaluate(
        self,
        case: EvalCase,
        raw: RawResult,
        assertion: AssertionSpec,
        config: LlmJudgeConfig,
    ) -> AssertionResult:
        raise NotImplementedError


class StubLlmJudgeProvider:
    def evaluate(
        self,
        case: EvalCase,
        raw: RawResult,
        assertion: AssertionSpec,
        config: LlmJudgeConfig,
    ) -> AssertionResult:  # noqa: ARG002
        if config.stub_result == "pass":
            return AssertionResult(
                type="llm_judge",
                metric=assertion.metric,
                passed=True,
                score=1.0,
                reason="stub llm judge pass",
            )
        if config.stub_result == "fail":
            return AssertionResult(
                type="llm_judge",
                metric=assertion.metric,
                passed=False,
                score=0.0,
                reason="stub llm judge fail",
            )
        return AssertionResult(
            type="llm_judge",
            metric=assertion.metric,
            passed=True,
            skipped=True,
            reason="llm judge skipped by offline stub",
        )


class DeepEvalJudgeProvider:
    def evaluate(
        self,
        case: EvalCase,
        raw: RawResult,
        assertion: AssertionSpec,
        config: LlmJudgeConfig,
    ) -> AssertionResult:
        metric_name = assertion.metric or "answer_relevancy"
        if metric_name not in SUPPORTED_DEEPEVAL_METRICS:
            return AssertionResult(
                type="llm_judge",
                metric=metric_name,
                passed=False,
                reason=f"unsupported llm_judge metric: {metric_name}",
            )
        input_text = _case_input(case.inputs)
        output_text = _actual_output(raw.response)
        if not input_text.strip():
            return AssertionResult(
                type="llm_judge",
                metric=metric_name,
                passed=False,
                reason="llm judge input is empty",
            )
        if not output_text.strip():
            return AssertionResult(
                type="llm_judge",
                metric=metric_name,
                passed=False,
                reason="llm judge actual_output is empty",
            )
        try:
            metrics_mod = importlib.import_module("deepeval.metrics")
            test_case_mod = importlib.import_module("deepeval.test_case")
            metric = metrics_mod.AnswerRelevancyMetric(
                threshold=config.threshold, model=config.model, include_reason=True
            )
            test_case = test_case_mod.LLMTestCase(
                input=input_text, actual_output=output_text
            )
            metric.measure(test_case)
        except ModuleNotFoundError as exc:
            if exc.name and exc.name.startswith("deepeval"):
                return AssertionResult(
                    type="llm_judge",
                    metric=metric_name,
                    passed=False,
                    reason="deepeval package is required for provider=deepeval; install agent-deepeval[deepeval]",
                )
            return _provider_error(metric_name, exc)
        except Exception as exc:  # noqa: BLE001 - provider errors become assertion failures
            return _provider_error(metric_name, exc)
        score = getattr(metric, "score", None)
        reason = _safe_reason(getattr(metric, "reason", ""))
        passed = bool(score is not None and score >= config.threshold)
        return AssertionResult(
            type="llm_judge",
            metric=metric_name,
            passed=passed,
            score=score,
            reason=reason,
        )


class LlmJudgeEvaluator:
    def __init__(self, config: LlmJudgeConfig):
        self.config = config

    def evaluate(self, case: EvalCase, raw: RawResult) -> list[AssertionResult]:
        results: list[AssertionResult] = []
        for assertion in case.assertions:
            if assertion.type != "llm_judge":
                continue
            if not self.config.enabled:
                results.append(
                    AssertionResult(
                        type="llm_judge",
                        metric=assertion.metric,
                        passed=True,
                        skipped=True,
                        reason="llm judge disabled",
                    )
                )
                continue
            provider = self._provider()
            results.append(provider.evaluate(case, raw, assertion, self.config))
        return results

    def _provider(self) -> LlmJudgeProvider:
        if self.config.provider == "stub":
            return StubLlmJudgeProvider()
        return DeepEvalJudgeProvider()


def _stable_json(value: Any) -> str:
    try:
        return json.dumps(redact(value), ensure_ascii=False, sort_keys=True)
    except TypeError:
        return str(redact(value))


def _case_input(inputs: dict[str, Any]) -> str:
    value = inputs.get("query")
    if value is None:
        return _stable_json(inputs)
    return str(value)


def _actual_output(response: Any) -> str:
    if isinstance(response, dict) and "answer" in response:
        value = response["answer"]
        return "" if value is None else str(value)
    return _stable_json(response)


def _safe_reason(reason: Any) -> str:
    text = redact_text(str(reason or "")) or ""
    return text if len(text) <= REASON_LIMIT else text[: REASON_LIMIT - 1] + "…"


def _provider_error(metric_name: str, exc: Exception) -> AssertionResult:
    return AssertionResult(
        type="llm_judge",
        metric=metric_name,
        passed=False,
        reason=_safe_reason(f"deepeval provider error: {exc}"),
    )
