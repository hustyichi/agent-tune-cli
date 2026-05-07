from __future__ import annotations

import json
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from agent_eval.models import EvalCase, RawResult
from agent_eval.runners.base import BaseRunner, error_result
from agent_eval.utils.redact import redact, redact_text


class ScriptRunner(BaseRunner):
    def __init__(self, command: str, cwd: Path, timeout: float):
        self.command = command
        self.cwd = cwd
        self.timeout = timeout

    def run_once(self, case: EvalCase, run_id: str) -> RawResult:
        start = time.perf_counter()
        case_payload = case.model_dump(mode="json")
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as tmp:
            json.dump(case_payload, tmp, ensure_ascii=False)
            input_file = Path(tmp.name)
        command = self.command.format(input_file=str(input_file))
        try:
            proc = subprocess.run(
                shlex.split(command),
                shell=False,
                cwd=self.cwd,
                text=True,
                capture_output=True,
                timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            input_file.unlink(missing_ok=True)
            return error_result(run_id, case, "timeout", start, f"Script timed out after {self.timeout}s", "timeout", stderr=redact_text(exc.stderr))
        finally:
            input_file.unlink(missing_ok=True)
        latency = (time.perf_counter() - start) * 1000
        if proc.returncode != 0:
            return RawResult(
                run_id=run_id,
                case_id=case.id,
                status="error",
                latency_ms=latency,
                request=redact({"inputs": case.inputs, "command": command}),
                response={},
                debug_meta={},
                error={"message": redact_text("Script exited nonzero"), "type": "process", "exit_code": proc.returncode, "stderr": redact_text(proc.stderr[-2000:])},
            )
        try:
            output = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError as exc:
            return RawResult(
                run_id=run_id,
                case_id=case.id,
                status="error",
                latency_ms=latency,
                request=redact({"inputs": case.inputs, "command": command}),
                response={},
                debug_meta={},
                error={"message": redact_text(f"Invalid JSON stdout: {exc}"), "type": "parse", "stderr": redact_text(proc.stderr[-2000:])},
            )
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
            request=redact({"inputs": case.inputs, "command": command}),
            response=redact(response),
            debug_meta=redact(debug_meta),
            error=None,
        )
