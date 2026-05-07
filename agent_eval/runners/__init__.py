from __future__ import annotations

from pathlib import Path

from agent_eval.models import EvalConfig
from agent_eval.runners.base import BaseRunner
from agent_eval.runners.http import HttpRunner
from agent_eval.runners.script import ScriptRunner


def build_runner(config: EvalConfig, cwd: Path) -> BaseRunner:
    if config.project.mode == "script":
        return ScriptRunner(config.target.script.command, cwd, config.runner.timeout_seconds)
    if config.project.mode == "http":
        return HttpRunner(config.target.http, cwd, config.runner.timeout_seconds)
    raise ValueError("adapter mode is reserved but not implemented in MVP")
