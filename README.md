# Agent-Eval-CLI

Agent-Eval-CLI is a local-first command-line tool for batch testing Agent/LLM applications, evaluating results, clustering failures, and generating local reports for later tuning work.

This repository currently implements the MVP described in `docs/prd.md` and planned in `.omx/plans/prd-agent-eval-cli-mvp.md`.

## MVP capabilities

- `agent-eval init` — create a local evaluation project with `eval.yaml`, sample cases, `runs/`, `reports/`, and a sample script target.
- `agent-eval run` — execute cases against a script or HTTP target, evaluate assertions, cluster failures, and write local artifacts.
- `agent-eval inspect` — inspect a run, case, or cluster from local files.
- `agent-eval compare` — compare two local runs and report pass-rate, case-transition, and cluster-transition deltas.
- `agent-eval export` — locate or print `repair_input.json` for downstream tuning tools.

Default generated projects run fully offline. LLM judging is represented as an optional provider boundary and defaults to a stub/disabled configuration; no API key or live LLM call is required for the sample workflow or tests.

## Install for development

```bash
python -m pip install -e '.[dev]'
```

## Quick start

```bash
mkdir /tmp/agent-eval-demo
cd /tmp/agent-eval-demo
agent-eval init
agent-eval run
agent-eval inspect --run latest
agent-eval compare --base latest --target latest
agent-eval export --run latest
```

A run writes:

- `runs/<run_id>/manifest.json`
- `runs/<run_id>/raw_results.jsonl`
- `runs/<run_id>/eval_results.jsonl`
- `runs/<run_id>/failures.jsonl`
- `runs/<run_id>/clusters.json`
- `runs/<run_id>/summary.md`
- `runs/<run_id>/repair_input.json`
- `reports/latest.md`


## Run comparison

V1.5 adds deterministic local run comparison without changing the normal `run` artifact contract:

```bash
agent-eval compare --base baseline --target target
agent-eval compare --base baseline --target target --show
agent-eval compare --base baseline --target target --output comparison.json
```

Default output is a concise human summary. `--show` prints machine-readable JSON, and `--output` writes that JSON to a requested path. Comparison output includes `cluster_key_version: "v1"`, pass-rate deltas, per-case transitions, and added/removed/persisted cluster IDs. Normal `agent-eval run` does not write comparison artifacts.

Failure signatures and repair input are enriched with optional, namespaced analysis fields while preserving existing fields for downstream compatibility. Cluster IDs keep the V1 grouping identity; richer signature fields improve titles and summaries but do not change the hash key.

## Target modes

### Script mode

`eval.yaml` can configure a command template:

```yaml
project:
  mode: script
target:
  script:
    command: "python sample_agent.py --input-file {input_file}"
```

The script receives a temporary case JSON file. It should print JSON to stdout, either:

```json
{"response": {"answer": "..."}, "debug_meta": {"route": "knowledge_qa"}}
```

or any plain JSON object, which is treated as the response.

### HTTP mode

HTTP mode supports URL, method, headers, timeout/retry settings, and a minimal payload mapping subset such as `$.inputs.query`.

If a JSON response contains `debug_meta`, Agent-Eval uses it for execution-semantic checks; otherwise the run behaves as a black-box evaluation.

## Assertions

MVP deterministic assertions include:

- `field_exists` / `jsonpath_exists` / `json_schema_match`
- `contains`
- `exact_match`
- `schema_keys`
- execution checks from `expected_execution` such as `expected_route`, `must_call_tools`, `forbid_tools`, `max_tool_calls`, and `min_retrieval_docs`
- `llm_judge` as an offline stub by default

## Privacy defaults

Artifacts are local files. Before writing request/response/debug/error/report data, Agent-Eval redacts common sensitive keys such as Authorization, Cookie, API keys, tokens, passwords, secrets, full prompts, and full intermediate context fields.

## Current non-goals

- No SaaS service or Web Dashboard
- No online observability/Langfuse dependency
- No automatic code patching, prompt modification, or PR creation
- No mandatory Claude Code runtime dependency
- No complete local adapter mode in this MVP
- No mandatory live LLM or DeepEval call in default workflows

## Verification

```bash
python -m pip install -e '.[dev]'
pytest
```
