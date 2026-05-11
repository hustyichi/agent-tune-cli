from __future__ import annotations

import json
import os
import subprocess
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from threading import Thread


def run_cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "agent_eval", *args], cwd=tmp_path, text=True, capture_output=True, env=env, check=True)


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_generated_project_e2e_offline(tmp_path: Path):
    run_cli(tmp_path, "init")
    assert (tmp_path / "eval.yaml").exists()
    assert (tmp_path / "cases" / "sample.jsonl").exists()
    cfg_text = (tmp_path / "eval.yaml").read_text()
    sample_agent = (tmp_path / "sample_agent.py").read_text()
    assert "mode: adapter" in cfg_text
    assert "module: sample_agent" in cfg_text
    assert "function: run" in cfg_text
    assert "def run(case:" in sample_agent
    assert "context" in sample_agent
    assert "argparse" not in sample_agent
    assert "--input-file" not in sample_agent
    assert "print(json.dumps" not in sample_agent
    assert "provider: stub" in cfg_text
    assert "llm_summary: false" in cfg_text
    assert "one case passes and one fails" in cfg_text

    result = run_cli(tmp_path, "run")
    assert "total=2" in result.stdout
    latest = tmp_path / "runs" / "latest.txt"
    assert latest.exists()
    run_id = latest.read_text().strip()
    run_dir = tmp_path / "runs" / run_id
    required = ["manifest.json", "raw_results.jsonl", "eval_results.jsonl", "failures.jsonl", "clusters.json", "summary.md", "repair_input.json"]
    for name in required:
        assert (run_dir / name).exists(), name
    assert not (run_dir / "attempts.jsonl").exists()

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["protocol_version"] == "agent-eval/v1alpha1"
    assert manifest["mode"] == "adapter"
    assert manifest["config_snapshot"]["project"]["mode"] == "adapter"
    assert manifest["config_snapshot"]["target"]["adapter"]["module"] == "sample_agent"
    assert manifest["config_snapshot"]["target"]["adapter"]["function"] == "run"
    assert manifest["evaluation"]["llm_judge"]["provider"] == "stub"
    raws = read_jsonl(run_dir / "raw_results.jsonl")
    evals = read_jsonl(run_dir / "eval_results.jsonl")
    failures = read_jsonl(run_dir / "failures.jsonl")
    assert all(r["protocol_version"] == "agent-eval/v1alpha1" for r in raws)
    assert raws[0]["response"]["answer"]
    assert raws[0]["debug_meta"]["route"] == "knowledge_qa"
    assert all("response" in r for r in raws)
    assert all("debug_meta" in r for r in raws)
    assert all("command" not in r["request"] for r in raws)
    assert all("input_file" not in r["request"] for r in raws)
    assert {e["case_id"] for e in evals} == {"sample_pass", "sample_fail"}
    outcomes = {e["case_id"]: e["passed"] for e in evals}
    assert outcomes == {"sample_pass": True, "sample_fail": False}
    assert [f["case_id"] for f in failures] == ["sample_fail"]
    assert evals[1]["failure_signature"]["root_cause"] == "route_mismatch"
    assert failures[0]["failure_signature"]["root_cause"] == "route_mismatch"

    inspect = run_cli(tmp_path, "inspect", "--run", "latest")
    assert "Cases: 2" in inspect.stdout
    case = run_cli(tmp_path, "inspect", "--run", "latest", "--case", "sample_fail")
    assert "sample_fail" in case.stdout
    clusters = json.loads((run_dir / "clusters.json").read_text())["clusters"]
    cluster = run_cli(tmp_path, "inspect", "--run", "latest", "--cluster", clusters[0]["cluster_id"])
    assert clusters[0]["cluster_id"] in cluster.stdout
    export = run_cli(tmp_path, "export", "--run", "latest")
    assert "repair_input.json" in export.stdout
    exported = json.loads(run_cli(tmp_path, "export", "--run", "latest", "--show").stdout)
    summary = (run_dir / "summary.md").read_text()
    repair = json.loads((run_dir / "repair_input.json").read_text())
    assert exported == repair
    assert "## Tag Breakdown" in summary
    assert "## Priority Breakdown" in summary
    assert "Representative cases:" in summary
    assert "Suggested investigation:" in summary
    assert repair["analysis"]["totals"]["total"] == 2
    assert repair["analysis"]["cluster_count"] == len(clusters)
    assert repair["analysis"]["tag_breakdown"]
    assert repair["analysis"]["priority_breakdown"]
    assert repair["clusters"][0]["cases"]
    assert repair["clusters"][0]["common_signature"]
    assert clusters[0]["common_signature"]["analysis"]["root_causes"] == ["route_mismatch"]
    assert clusters[0]["common_signature"]["analysis"]["root_cause_counts"] == {"route_mismatch": 1}
    assert clusters[0]["common_signature"]["analysis"]["common_root_cause"] == "route_mismatch"
    assert repair["clusters"][0]["analysis"]["root_causes"] == ["route_mismatch"]
    assert repair["clusters"][0]["analysis"]["root_cause_counts"] == {"route_mismatch": 1}
    assert repair["clusters"][0]["analysis"]["common_root_cause"] == "route_mismatch"
    assert "Root cause: route_mismatch" in summary
    assert repair["clusters"][0]["suspected_modules"] == []
    assert repair["clusters"][0]["evidence"]
    assert repair["clusters"][0]["analysis"]["representative_cases"]
    assert repair["clusters"][0]["analysis"]["suggested_investigation"] in summary
    same_run_compare = json.loads(run_cli(tmp_path, "compare", "--base", "latest", "--target", "latest", "--show").stdout)
    assert same_run_compare["base_run_id"] == run_id
    assert same_run_compare["target_run_id"] == run_id
    assert same_run_compare["totals"]["pass_rate_delta"] == 0
    assert (tmp_path / "reports" / "latest.md").exists()


def test_adapter_runner_cli_e2e(tmp_path: Path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "eval.yaml").write_text("""
project:
  name: adapter-agent
  mode: adapter
runner:
  concurrency: 1
  timeout_seconds: 5
  retry_times: 0
target:
  adapter:
    module: local_adapter
    function: run
dataset:
  paths: [cases/adapter.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
    (tmp_path / "local_adapter.py").write_text("""
def run(case):
    query = case['inputs']['query']
    return {
        'response': {'answer': f'adapter echo {query}'},
        'debug_meta': {'route': 'adapter', 'tool_calls': [{'name': 'local.run'}]},
    }
""".strip())
    (tmp_path / "cases" / "adapter.jsonl").write_text('{"id":"a1","inputs":{"query":"hello"},"assertions":[{"type":"contains","target":"$.answer","expected":"hello"}],"expected_execution":{"expected_route":"adapter","must_call_tools":["local.run"]}}\n')

    result = run_cli(tmp_path, "run")

    assert "total=1" in result.stdout
    run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
    run_dir = tmp_path / "runs" / run_id
    required = ["manifest.json", "raw_results.jsonl", "eval_results.jsonl", "failures.jsonl", "clusters.json", "summary.md", "repair_input.json"]
    for name in required:
        assert (run_dir / name).exists(), name
    raw = read_jsonl(run_dir / "raw_results.jsonl")[0]
    eval_result = read_jsonl(run_dir / "eval_results.jsonl")[0]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert raw["status"] == "success"
    assert raw["response"]["answer"] == "adapter echo hello"
    assert raw["request"] == {"inputs": {"query": "hello"}}
    assert "command" not in raw["request"]
    assert "input_file" not in raw["request"]
    assert raw["debug_meta"]["route"] == "adapter"
    assert raw["debug_meta"]["tool_calls"][0]["name"] == "local.run"
    assert eval_result["passed"] is True
    assert manifest["mode"] == "adapter"
    assert manifest["config_snapshot"]["project"]["mode"] == "adapter"
    assert manifest["config_snapshot"]["target"]["adapter"]["module"] == "local_adapter"


def test_adapter_runner_cli_defaults_function_to_run(tmp_path: Path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "eval.yaml").write_text("""
project:
  name: adapter-default-function
  mode: adapter
runner:
  concurrency: 1
  timeout_seconds: 5
target:
  adapter:
    module: local_adapter
dataset:
  paths: [cases/adapter.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
    (tmp_path / "local_adapter.py").write_text("""
def run(case):
    return {"response": {"answer": case["inputs"]["query"]}, "debug_meta": {"route": "default_run"}}
""".strip())
    (tmp_path / "cases" / "adapter.jsonl").write_text(
        '{"id":"a1","inputs":{"query":"hello"},"assertions":[{"type":"contains","target":"$.answer","expected":"hello"}],"expected_execution":{"expected_route":"default_run"}}\n'
    )

    run_cli(tmp_path, "run")

    run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
    run_dir = tmp_path / "runs" / run_id
    raw = read_jsonl(run_dir / "raw_results.jsonl")[0]
    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert raw["status"] == "success"
    assert raw["debug_meta"]["route"] == "default_run"
    assert manifest["config_snapshot"]["target"]["adapter"]["function"] == "run"


def test_evaluation_policy_reruns_write_attempt_sidecar_and_preserve_consumers(tmp_path: Path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "eval.yaml").write_text("""
project:
  name: rerun-agent
  mode: adapter
runner:
  concurrency: 1
  timeout_seconds: 5
  retry_times: 0
target:
  adapter:
    module: rerun_adapter
    function: run
dataset:
  paths: [cases/rerun.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
    (tmp_path / "rerun_adapter.py").write_text("""
from pathlib import Path

def run(case):
    counter = Path('counter.txt')
    n = int(counter.read_text()) if counter.exists() else 0
    counter.write_text(str(n + 1))
    answer = 'ok' if n == 1 else 'miss'
    return {
        'response': {'answer': answer, 'attempt_number': n + 1},
        'debug_meta': {'route': 'rerun', 'tool_calls': []},
    }
""".strip())
    (tmp_path / "cases" / "rerun.jsonl").write_text(
        '{"id":"r1","inputs":{"query":"hello"},"assertions":[{"type":"contains","target":"$.answer","expected":"ok"}],"evaluation_policy":{"reruns":2,"pass_rule":"any"}}\n'
    )

    run_cli(tmp_path, "run", "--run-name", "rerun-any")
    run_dir = tmp_path / "runs" / "rerun-any"
    raw_rows = read_jsonl(run_dir / "raw_results.jsonl")
    eval_rows = read_jsonl(run_dir / "eval_results.jsonl")
    attempt_rows = read_jsonl(run_dir / "attempts.jsonl")

    assert len(raw_rows) == 1
    assert len(eval_rows) == 1
    assert eval_rows[0]["case_id"] == "r1"
    assert eval_rows[0]["passed"] is True
    assert raw_rows[0]["response"]["answer"] == "ok"
    assert raw_rows[0]["metadata"]["evaluation_attempt_index"] == 1
    assert raw_rows[0]["metadata"]["evaluation_attempt_count"] == 3
    assert [row["evaluation_attempt_index"] for row in attempt_rows] == [0, 1, 2]
    assert [row["passed"] for row in attempt_rows] == [False, True, False]
    assert all(row["case_id"] == "r1" for row in attempt_rows)
    assert all(row["raw_result"]["attempt_count"] == 1 for row in attempt_rows)

    inspect = run_cli(tmp_path, "inspect", "--run", "rerun-any", "--case", "r1")
    assert '"case_id": "r1"' in inspect.stdout
    export = run_cli(tmp_path, "export", "--run", "rerun-any")
    assert "repair_input.json" in export.stdout

    (tmp_path / "counter.txt").unlink()
    run_cli(tmp_path, "run", "--run-name", "rerun-any-2")
    comparison = json.loads(run_cli(tmp_path, "compare", "--base", "rerun-any", "--target", "rerun-any-2", "--show").stdout)
    assert comparison["case_transitions"][0]["case_id"] == "r1"


def test_evaluation_reruns_are_distinct_from_runner_retries(tmp_path: Path):
    (tmp_path / "cases").mkdir()
    (tmp_path / "runs").mkdir()
    (tmp_path / "reports").mkdir()
    (tmp_path / "eval.yaml").write_text("""
project:
  name: retry-vs-rerun
  mode: script
runner:
  concurrency: 1
  timeout_seconds: 5
  retry_times: 1
target:
  script:
    command: "{python} flaky.py --input-file {input_file}"
dataset:
  paths: [cases/retry.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
    (tmp_path / "flaky.py").write_text("""
import argparse, json, pathlib, sys
parser = argparse.ArgumentParser()
parser.add_argument('--input-file', required=True)
parser.parse_args()
counter = pathlib.Path('counter.txt')
n = int(counter.read_text()) if counter.exists() else 0
counter.write_text(str(n + 1))
if n % 2 == 0:
    sys.exit(1)
print(json.dumps({'response': {'answer': 'ok'}, 'debug_meta': {'route': 'script'}}))
""".strip())
    (tmp_path / "cases" / "retry.jsonl").write_text(
        '{"id":"retry","assertions":[{"type":"contains","target":"$.answer","expected":"ok"}],"evaluation_policy":{"reruns":1,"pass_rule":"all"}}\n'
    )

    run_cli(tmp_path, "run")
    run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
    attempts = read_jsonl(tmp_path / "runs" / run_id / "attempts.jsonl")

    assert len(attempts) == 2
    assert [row["evaluation_attempt_index"] for row in attempts] == [0, 1]
    assert [row["raw_result"]["attempt_count"] for row in attempts] == [2, 2]
    assert all(row["passed"] for row in attempts)


def test_redaction_in_e2e_artifacts(tmp_path: Path):
    run_cli(tmp_path, "init")
    # Add a case carrying sentinel secret fields; sample agent echoes only response/debug_meta,
    # but request artifacts include inputs and must redact the token-like key.
    with (tmp_path / "cases" / "sample.jsonl").open("a") as fh:
        fh.write('{"id":"secret_case","inputs":{"query":"route knowledge pricing","api_key":"SENTINEL_SECRET"},"assertions":[{"type":"contains","target":"$.answer","expected":"pricing"}]}\n')
    run_cli(tmp_path, "run")
    run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
    combined = "\n".join(p.read_text() for p in (tmp_path / "runs" / run_id).iterdir() if p.is_file())
    assert "SENTINEL_SECRET" not in combined
    assert "[REDACTED]" in combined


class JsonHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("content-length", "0"))
        payload = json.loads(self.rfile.read(length) or b"{}")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"response": {"answer": f"echo {payload['query']}"}, "debug_meta": {"route": "http", "tool_calls": []}}).encode())

    def log_message(self, format, *args):  # noqa: A003
        return


def test_http_runner_with_local_server(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), JsonHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        (tmp_path / "cases").mkdir()
        (tmp_path / "runs").mkdir()
        (tmp_path / "reports").mkdir()
        port = server.server_address[1]
        (tmp_path / "eval.yaml").write_text(f"""
project:
  name: http-agent
  mode: http
runner:
  concurrency: 1
  timeout_seconds: 5
  retry_times: 0
target:
  http:
    url: "http://127.0.0.1:{port}/chat"
    method: "POST"
    headers:
      Authorization: "Bearer SENTINEL_SECRET"
    payload_mapping:
      query: "$.inputs.query"
dataset:
  paths: [cases/http.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
        (tmp_path / "cases" / "http.jsonl").write_text('{"id":"h1","inputs":{"query":"hello"},"assertions":[{"type":"contains","target":"$.answer","expected":"hello"}],"expected_execution":{"expected_route":"http"}}\n')
        run_cli(tmp_path, "run")
        run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
        raw = read_jsonl(tmp_path / "runs" / run_id / "raw_results.jsonl")[0]
        assert raw["status"] == "success"
        assert raw["metadata"]["status_code"] == 200
        assert raw["request"]["headers"]["Authorization"] == "[REDACTED]"
        assert raw["debug_meta"]["route"] == "http"
        manifest = json.loads((tmp_path / "runs" / run_id / "manifest.json").read_text())
        assert manifest["config_snapshot"]["target"]["http"]["headers"]["Authorization"] == "[REDACTED]"
    finally:
        server.shutdown()


def test_run_name_path_traversal_rejected(tmp_path: Path):
    run_cli(tmp_path, "init")
    env = os.environ.copy()
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-m", "agent_eval", "run", "--run-name", "../SENTINEL_OUTSIDE_RUN"], cwd=tmp_path, text=True, capture_output=True, env=env)
    assert proc.returncode != 0
    assert not (tmp_path.parent / "SENTINEL_OUTSIDE_RUN").exists()

class ErrorHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(500)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"error":"bad"}')

    def log_message(self, format, *args):  # noqa: A003
        return


class InvalidJsonHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b'not-json')

    def log_message(self, format, *args):  # noqa: A003
        return


def write_http_project(tmp_path: Path, port: int):
    (tmp_path / "cases").mkdir(exist_ok=True)
    (tmp_path / "runs").mkdir(exist_ok=True)
    (tmp_path / "reports").mkdir(exist_ok=True)
    (tmp_path / "eval.yaml").write_text(f"""
project:
  name: http-agent
  mode: http
runner:
  concurrency: 1
  timeout_seconds: 1
  retry_times: 0
target:
  http:
    url: "http://127.0.0.1:{port}/chat"
    method: "POST"
    headers:
      Authorization: "Bearer SENTINEL_SECRET"
    payload_mapping:
      query: "$.inputs.query"
dataset:
  paths: [cases/http.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
    (tmp_path / "cases" / "http.jsonl").write_text('{"id":"h1","inputs":{"query":"hello"},"assertions":[{"type":"contains","target":"$.answer","expected":"hello"}]}\n')


def test_http_runner_non_2xx_and_invalid_json_paths(tmp_path: Path):
    server = HTTPServer(("127.0.0.1", 0), ErrorHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        write_http_project(tmp_path, server.server_address[1])
        run_cli(tmp_path, "run")
        run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
        raw = read_jsonl(tmp_path / "runs" / run_id / "raw_results.jsonl")[0]
        assert raw["status"] == "error"
        assert raw["metadata"]["status_code"] == 500
    finally:
        server.shutdown()

    other = tmp_path / "invalid"
    other.mkdir()
    server = HTTPServer(("127.0.0.1", 0), InvalidJsonHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        write_http_project(other, server.server_address[1])
        run_cli(other, "run")
        run_id = (other / "runs" / "latest.txt").read_text().strip()
        raw = read_jsonl(other / "runs" / run_id / "raw_results.jsonl")[0]
        assert raw["status"] == "error"
        assert raw["error"]["type"] == "parse"
        assert raw["metadata"]["status_code"] == 200
    finally:
        server.shutdown()


def test_export_inspect_reject_run_traversal(tmp_path: Path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "run")
    env = os.environ.copy()
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    for command in ("export", "inspect"):
        proc = subprocess.run([sys.executable, "-m", "agent_eval", command, "--run", "../outside"], cwd=tmp_path, text=True, capture_output=True, env=env)
        assert proc.returncode != 0

def test_script_command_secret_redacted_from_manifest_and_raw(tmp_path: Path):
    run_cli(tmp_path, "init")
    (tmp_path / "eval.yaml").write_text("""
project:
  name: script-secret
  mode: script
runner:
  concurrency: 1
  timeout_seconds: 5
  retry_times: 0
target:
  script:
    command: "{python} sample_agent.py --api-key sk-live-abc123 --input-file {input_file}"
dataset:
  paths: [cases/sample.jsonl]
evaluation:
  llm_judge:
    enabled: false
    provider: stub
cluster:
  enabled: true
  llm_summary: false
artifacts:
  root_dir: ./runs
  reports_dir: ./reports
""")
    (tmp_path / "sample_agent.py").write_text("""
import argparse, json
parser = argparse.ArgumentParser()
parser.add_argument("--api-key", required=False)
parser.add_argument("--input-file", required=True)
args = parser.parse_args()
case = json.load(open(args.input_file))
print(json.dumps({"response": {"answer": case.get("inputs", {}).get("query", "")}, "debug_meta": {"route": "script"}}))
""".strip())
    run_cli(tmp_path, "run")
    run_id = (tmp_path / "runs" / "latest.txt").read_text().strip()
    combined = "\n".join(p.read_text() for p in (tmp_path / "runs" / run_id).iterdir() if p.is_file())
    assert "sk-live-abc123" not in combined
    assert "[REDACTED]" in combined


def test_compare_generated_runs_e2e(tmp_path: Path):
    run_cli(tmp_path, "init")
    run_cli(tmp_path, "run", "--run-name", "baseline")
    sample = tmp_path / "cases" / "sample.jsonl"
    sample.write_text(sample.read_text().replace("no retrieval please", "route knowledge pricing"))
    run_cli(tmp_path, "run", "--run-name", "target")

    shown = run_cli(tmp_path, "compare", "--base", "baseline", "--target", "target", "--show")
    comparison = json.loads(shown.stdout)
    assert comparison["base_run_id"] == "baseline"
    assert comparison["target_run_id"] == "target"
    assert comparison["cluster_key_version"] == "v1"
    transitions = {item["case_id"]: item["transition"] for item in comparison["case_transitions"]}
    assert transitions["sample_fail"] == "failed_to_passed"
    assert comparison["totals"]["pass_rate_delta"] > 0

    out = tmp_path / "comparison.json"
    default = run_cli(tmp_path, "compare", "--base", "baseline", "--target", "target", "--output", str(out))
    assert "baseline -> target" in default.stdout
    assert out.exists()
    assert json.loads(out.read_text())["cluster_key_version"] == "v1"


def test_generated_project_runs_without_python_on_path(tmp_path: Path):
    run_cli(tmp_path, "init")
    no_python_bin = tmp_path / "no-python-bin"
    no_python_bin.mkdir()
    env = os.environ.copy()
    repo = Path(__file__).resolve().parents[1]
    env["PYTHONPATH"] = str(repo) + os.pathsep + env.get("PYTHONPATH", "")
    env["PATH"] = str(no_python_bin)

    proc = subprocess.run([sys.executable, "-m", "agent_eval", "run"], cwd=tmp_path, text=True, capture_output=True, env=env, check=True)

    assert "total=2" in proc.stdout
