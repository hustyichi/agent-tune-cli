from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from agent_eval.models import EvalCase, HttpTargetConfig, RawResult
from agent_eval.runners.base import BaseRunner, error_result
from agent_eval.utils.jsonpath import map_payload
from agent_eval.utils.redact import redact


class HttpRunner(BaseRunner):
    def __init__(self, config: HttpTargetConfig, cwd: Path, timeout: float):
        self.config = config
        self.cwd = cwd
        self.timeout = timeout

    def run_once(self, case: EvalCase, run_id: str) -> RawResult:
        start = time.perf_counter()
        try:
            payload = map_payload(case.inputs, self.config.payload_mapping)
        except ValueError as exc:
            return error_result(run_id, case, "error", start, str(exc), "config")
        try:
            resp = httpx.request(
                self.config.method,
                self.config.url,
                headers=self.config.headers,
                json=payload,
                timeout=self.timeout,
            )
        except httpx.TimeoutException:
            return error_result(
                run_id,
                case,
                "timeout",
                start,
                f"HTTP timed out after {self.timeout}s",
                "timeout",
            )
        except httpx.HTTPError as exc:
            return error_result(run_id, case, "error", start, str(exc), "http")
        latency = (time.perf_counter() - start) * 1000
        try:
            body: Any = resp.json()
        except ValueError as exc:
            return RawResult(
                run_id=run_id,
                case_id=case.id,
                status="error",
                latency_ms=latency,
                request=redact({"headers": self.config.headers, "payload": payload}),
                response={"status_code": resp.status_code},
                debug_meta={},
                metadata={"status_code": resp.status_code},
                error={"message": f"Invalid JSON response: {exc}", "type": "parse"},
            )
        debug_meta = body.get("debug_meta", {}) if isinstance(body, dict) else {}
        response = body.get("response", body) if isinstance(body, dict) else body
        status = "success" if 200 <= resp.status_code < 300 else "error"
        return RawResult(
            run_id=run_id,
            case_id=case.id,
            status=status,
            latency_ms=latency,
            request=redact({"headers": self.config.headers, "payload": payload}),
            response=redact(response),
            debug_meta=redact(debug_meta),
            error=None
            if status == "success"
            else {"message": f"HTTP status {resp.status_code}", "type": "http"},
            metadata={"status_code": resp.status_code},
        )
