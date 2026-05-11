from __future__ import annotations

import importlib
import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_eval.models import AdapterTargetConfig, EvalCase, RawResult
from agent_eval.runners.base import BaseRunner, error_result
from agent_eval.utils.redact import redact


class PythonAdapterRunner(BaseRunner):
    def __init__(self, config: AdapterTargetConfig, cwd: Path, timeout: float):
        self.config = config
        self.cwd = cwd
        self.timeout = timeout
        self._callable: Callable[[dict[str, Any]], Any] | None = None
        self._load_error: Exception | None = None
        if not config.module:
            raise ValueError(
                "target.adapter.module is required when project.mode is adapter"
            )
        self._resolve_callable()

    def _resolve_callable(self) -> None:
        original_path = list(sys.path)
        cwd_text = str(self.cwd)
        try:
            if cwd_text not in sys.path:
                sys.path.insert(0, cwd_text)
            module = importlib.import_module(self.config.module)
            candidate = getattr(module, self.config.function)
            if not callable(candidate):
                raise TypeError(
                    f"target.adapter.function is not callable: {self.config.function}"
                )
            self._callable = candidate
        except Exception as exc:  # noqa: BLE001 - deferred to per-case RawResult
            self._load_error = exc
        finally:
            sys.path[:] = original_path

    def run_once(self, case: EvalCase, run_id: str) -> RawResult:
        start = time.perf_counter()
        if self._load_error is not None:
            return error_result(
                run_id, case, "error", start, str(self._load_error), "adapter"
            )
        assert self._callable is not None
        try:
            output = self._callable(case.model_dump(mode="json"))
        except TimeoutError as exc:
            return error_result(run_id, case, "timeout", start, str(exc), "timeout")
        except Exception as exc:  # noqa: BLE001 - adapter failures become result artifacts
            return error_result(run_id, case, "error", start, str(exc), "adapter")

        latency = (time.perf_counter() - start) * 1000
        if isinstance(output, dict) and "response" in output:
            response = output.get("response") or {}
            debug_meta = output.get("debug_meta") or {}
        else:
            response = output
            debug_meta = {}
        return RawResult(
            run_id=run_id,
            case_id=case.id,
            status="success",
            latency_ms=latency,
            request=redact({"inputs": case.inputs}),
            response=redact(response),
            debug_meta=redact(debug_meta),
            error=None,
        )
