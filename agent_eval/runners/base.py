from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from agent_eval.models import EvalCase, RawResult, ErrorInfo
from agent_eval.utils.redact import redact, redact_text


class BaseRunner(ABC):
    @abstractmethod
    def run_once(self, case: EvalCase, run_id: str) -> RawResult:
        raise NotImplementedError

    def run_with_retries(
        self, case: EvalCase, run_id: str, retry_times: int
    ) -> RawResult:
        attempts = 0
        last: RawResult | None = None
        for attempts in range(1, retry_times + 2):
            last = self.run_once(case, run_id)
            last.attempt_count = attempts
            if last.status == "success":
                return last
        assert last is not None
        last.attempt_count = attempts
        return last


def error_result(
    run_id: str,
    case: EvalCase,
    status: str,
    start: float,
    message: str,
    error_type: str = "error",
    **kwargs: Any,
) -> RawResult:
    return RawResult(
        run_id=run_id,
        case_id=case.id,
        status=status,  # type: ignore[arg-type]
        latency_ms=(time.perf_counter() - start) * 1000,
        request=redact({"inputs": case.inputs}),
        response={},
        debug_meta={},
        error=ErrorInfo(
            message=redact_text(message) or "",
            type=error_type,
            **{
                k: redact_text(v) if isinstance(v, str) else redact(v)
                for k, v in kwargs.items()
            },
        ),
    )
