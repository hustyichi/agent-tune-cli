from __future__ import annotations

import json
import sys
import uuid
from pathlib import Path

import pytest

from agent_eval.config import load_config
from agent_eval.evaluators import evaluate_case
from agent_eval.models import EvalCase
from agent_eval.runners import build_runner
from agent_eval.runners.adapter import PythonAdapterRunner
from agent_eval.runners.http import HttpRunner
from agent_eval.runners.script import ScriptRunner
from agent_eval.utils.redact import REDACTED


def write_module(tmp_path: Path, body: str) -> str:
    name = f"adapter_{uuid.uuid4().hex}"
    (tmp_path / f"{name}.py").write_text(body)
    return name


def adapter_config(tmp_path: Path, module: str, function: str = "run"):
    path = tmp_path / "eval.yaml"
    path.write_text(
        f"""
project:
  name: adapter-agent
  mode: adapter
target:
  adapter:
    module: {module}
    function: {function}
evaluation:
  llm_judge:
    enabled: false
    provider: stub
"""
    )
    return load_config(path)


def test_existing_script_and_http_configs_do_not_require_adapter(tmp_path: Path):
    script_config = load_config(Path("does-not-exist.yaml"))
    assert script_config.project.mode == "script"
    assert isinstance(build_runner(script_config, tmp_path), ScriptRunner)
    assert script_config.target.adapter.module == ""
    assert script_config.target.adapter.function == "run"

    http_config_path = tmp_path / "http.yaml"
    http_config_path.write_text(
        """
project:
  mode: http
target:
  http:
    url: http://127.0.0.1:1/chat
"""
    )
    http_config = load_config(http_config_path)
    assert isinstance(build_runner(http_config, tmp_path), HttpRunner)
    assert http_config.target.adapter.function == "run"


def test_adapter_runner_dispatch_requires_module_only_in_adapter_mode(tmp_path: Path):
    cfg_path = tmp_path / "eval.yaml"
    cfg_path.write_text("project:\n  mode: adapter\n")
    cfg = load_config(cfg_path)

    with pytest.raises(ValueError, match="target.adapter.module"):
        build_runner(cfg, tmp_path)


def test_adapter_runner_reports_missing_function_as_adapter_error(tmp_path: Path):
    module = write_module(tmp_path, "ANSWER = {'answer': 'ok'}")
    runner = build_runner(
        adapter_config(tmp_path, module, function="missing"), tmp_path
    )
    case = EvalCase.model_validate({"id": "missing-function"})

    result = runner.run_once(case, "r1")

    assert result.status == "error"
    assert result.error and result.error.type == "adapter"
    assert "missing" in result.error.message


def test_adapter_runner_returns_response_and_debug_meta(tmp_path: Path):
    module = write_module(
        tmp_path,
        """
def run(case):
    assert case["id"] == "c1"
    return {
        "response": {"answer": "pricing details"},
        "debug_meta": {
            "route": "knowledge_qa",
            "retrieval_doc_count": 1,
            "tool_calls": [{"name": "retriever.search"}],
        },
    }
""".strip(),
    )
    runner = build_runner(adapter_config(tmp_path, module), tmp_path)
    case = EvalCase.model_validate(
        {
            "id": "c1",
            "inputs": {"query": "pricing"},
            "assertions": [
                {"type": "contains", "target": "$.answer", "expected": "pricing"}
            ],
            "expected_execution": {
                "expected_route": "knowledge_qa",
                "must_call_tools": ["retriever.search"],
                "min_retrieval_docs": 1,
            },
        }
    )

    raw = runner.run_once(case, "r1")
    result = evaluate_case(
        "r1", case, raw, load_config(Path("does-not-exist.yaml")).evaluation.llm_judge
    )

    assert raw.status == "success"
    assert raw.request == {"inputs": {"query": "pricing"}}
    assert "command" not in raw.request
    assert "input_file" not in raw.request
    assert raw.response == {"answer": "pricing details"}
    assert raw.debug_meta["route"] == "knowledge_qa"
    assert result.passed is True


def test_adapter_runner_receives_full_case_shape(tmp_path: Path):
    module = write_module(
        tmp_path,
        """
def run(case):
    return {
        "response": {
            "id": case["id"],
            "query": case["inputs"]["query"],
            "product": case["context"]["product"],
            "assertion_type": case["assertions"][0]["type"],
            "route": case["expected_execution"]["expected_route"],
            "pass_rule": case["evaluation_policy"]["pass_rule"],
        },
        "debug_meta": {"route": "case_shape"},
    }
""".strip(),
    )
    runner = build_runner(adapter_config(tmp_path, module), tmp_path)
    case = EvalCase.model_validate(
        {
            "id": "shape",
            "inputs": {"query": "pricing"},
            "context": {"product": "pricing"},
            "assertions": [
                {"type": "contains", "target": "$.answer", "expected": "pricing"}
            ],
            "expected_execution": {"expected_route": "case_shape"},
            "evaluation_policy": {"pass_rule": "any"},
        }
    )

    raw = runner.run_once(case, "r1")

    assert raw.status == "success"
    assert raw.response == {
        "id": "shape",
        "query": "pricing",
        "product": "pricing",
        "assertion_type": "contains",
        "route": "case_shape",
        "pass_rule": "any",
    }
    assert raw.debug_meta == {"route": "case_shape"}


def test_adapter_runner_accepts_raw_response_without_debug_meta(tmp_path: Path):
    module = write_module(
        tmp_path,
        """
def run(case):
    return {"answer": case["inputs"]["query"]}
""".strip(),
    )
    runner = build_runner(adapter_config(tmp_path, module), tmp_path)
    case = EvalCase.model_validate({"id": "raw", "inputs": {"query": "hello"}})

    raw = runner.run_once(case, "r1")

    assert raw.status == "success"
    assert raw.response == {"answer": "hello"}
    assert raw.debug_meta == {}


def test_adapter_runner_redacts_exceptions_and_classifies_timeout(tmp_path: Path):
    error_module = write_module(
        tmp_path,
        """
def run(case):
    raise RuntimeError("SENTINEL_SECRET_TOKEN")
""".strip(),
    )
    timeout_module = write_module(
        tmp_path,
        """
def run(case):
    raise TimeoutError("adapter timed out")
""".strip(),
    )
    case = EvalCase.model_validate(
        {"id": "bad", "inputs": {"api_key": "SENTINEL_API_KEY"}}
    )

    error_result = build_runner(
        adapter_config(tmp_path, error_module), tmp_path
    ).run_once(case, "r1")
    timeout_result = build_runner(
        adapter_config(tmp_path, timeout_module), tmp_path
    ).run_once(case, "r1")

    dumped = json.dumps(error_result.model_dump(mode="json"))
    assert error_result.status == "error"
    assert error_result.error and error_result.error.type == "adapter"
    assert "SENTINEL_SECRET_TOKEN" not in dumped
    assert "SENTINEL_API_KEY" not in dumped
    assert REDACTED in dumped
    assert timeout_result.status == "timeout"
    assert timeout_result.error and timeout_result.error.type == "timeout"


def test_adapter_runner_restores_sys_path_after_import(tmp_path: Path):
    module = write_module(
        tmp_path,
        """
def run(case):
    return {"answer": "ok"}
""".strip(),
    )
    before = list(sys.path)
    try:
        runner = build_runner(adapter_config(tmp_path, module), tmp_path)
        assert list(sys.path) == before
        sys.path.insert(0, str(tmp_path))
        try:
            (tmp_path / f"{module}.py").write_text(
                "def run(case):\n    return {'answer': 'changed'}\n"
            )
            case = EvalCase.model_validate({"id": "cache"})
            raw = runner.run_once(case, "r1")
            assert raw.response == {"answer": "ok"}
        finally:
            sys.path.remove(str(tmp_path))
    finally:
        sys.modules.pop(module, None)


def test_generated_adapter_template_imports_without_io_boilerplate(tmp_path: Path):
    from importlib import resources

    eval_yaml = (
        resources.files("agent_eval.templates").joinpath("eval.yaml").read_text()
    )
    sample_agent = (
        resources.files("agent_eval.templates").joinpath("sample_agent.py").read_text()
    )
    (tmp_path / "eval.yaml").write_text(eval_yaml)
    (tmp_path / "sample_agent.py").write_text(sample_agent)
    try:
        config = load_config(tmp_path / "eval.yaml")
        runner = build_runner(config, tmp_path)
        case = EvalCase.model_validate(
            {
                "id": "generated",
                "inputs": {"query": "route knowledge pricing"},
                "context": {"product": "pricing"},
            }
        )

        raw = runner.run_once(case, "r1")

        assert config.project.mode == "adapter"
        assert config.target.adapter.module == "sample_agent"
        assert config.target.adapter.function == "run"
        assert isinstance(runner, PythonAdapterRunner)
        assert "argparse" not in sample_agent
        assert "--input-file" not in sample_agent
        assert "print(json.dumps" not in sample_agent
        assert raw.status == "success"
        assert raw.response["answer"]
        assert raw.debug_meta["route"] == "knowledge_qa"
    finally:
        sys.modules.pop("sample_agent", None)
