# Agent-Eval

[![PyPI](https://img.shields.io/pypi/v/agent-deepeval.svg)](https://pypi.org/project/agent-deepeval/)

Local-first CLI for batch-evaluating AI Agents, clustering failures, and tracking regressions — all without leaving your machine.

The package is published as **`agent-deepeval`** on PyPI; the installed command is **`agent-eval`**.

## Highlights

- **Fully offline by default** — no API keys, no SaaS, no live LLM calls required. Every evaluation runs on local files with deterministic rule assertions.
- **Three target modes** — test local scripts (`mode: script`), HTTP APIs (`mode: http`), or in-process Python functions (`mode: adapter`) without changing your test cases.
- **Automatic failure clustering** — failed cases are grouped by failure signature (error code, route, tool, assertion type, tags, etc.) so you can fix batches of problems at once.
- **Run comparison & regression tracking** — `agent-eval compare` shows pass-rate deltas, per-case transitions (passed↔failed), and cluster evolution between any two runs.
- **Repair export** — `agent-eval export` produces a structured `repair_input.json` with clustered evidence for downstream tuning pipelines.
- **Privacy-first** — artifacts are local files; sensitive keys (Authorization, Cookie, API keys, tokens, passwords, prompts) are redacted before writing.
- **Opt-in LLM judging** — swap the stub judge for DeepEval's `answer_relevancy` metric when you need semantic scoring.

## Install

```bash
pip install agent-deepeval
agent-eval --help
```

For development:

```bash
pip install -e '.[dev,release]'
```

## Core workflow

```
init → write test cases → run (execute + evaluate + cluster) → inspect / compare → export
```

### 1. Initialize a project

```bash
mkdir my-agent-eval && cd my-agent-eval
agent-eval init
```

This scaffolds:

| File/Dir | Purpose |
|----------|---------|
| `eval.yaml` | Project configuration (target mode, evaluation rules, clustering settings) |
| `cases/sample.jsonl` | Example test cases |
| `sample_agent.py` | Example Agent script |
| `runs/` | Artifact output directory |
| `reports/` | Human-readable summary reports |

### 2. Write test cases

Each line in `cases/*.jsonl` is a test case:

```json
{
  "id": "pricing-query",
  "tags": ["smoke", "rag"],
  "priority": "p1",
  "inputs": { "query": "What is the pricing for product X?" },
  "assertions": [
    { "type": "contains", "target": "$.answer", "expected": "pricing" }
  ],
  "expected_execution": {
    "expected_route": "knowledge_qa",
    "must_call_tools": ["retriever.search"],
    "min_retrieval_docs": 1
  }
}
```

Assertions supported out of the box:

- `contains` / `exact_match` — string and value matching
- `field_exists` / `jsonpath_exists` — presence checks
- `json_schema_match` / `schema_keys` — object shape validation
- `numeric_threshold` — numeric comparisons (`gt`, `gte`, `lt`, `lte`, `eq`)
- `http_status` — HTTP response code checks
- `expected_execution` — semantic checks (route, tool calls, retrieval doc count, fallback behavior)
- `llm_judge` — LLM-as-judge (stub by default; opt-in DeepEval)

### 3. Run evaluation

```bash
agent-eval run
```

The pipeline executes in sequence:

1. **Run Agent** — sends each test case to your Agent (script, HTTP, or Python adapter)
2. **Evaluate** — checks every assertion against the Agent's response
3. **Cluster failures** — groups failed cases by their failure signature
4. **Write artifacts** — saves all results to `runs/<run_id>/`

```
runs/<run_id>/
├── manifest.json        # run metadata and config snapshot
├── raw_results.jsonl    # raw Agent responses
├── eval_results.jsonl   # assertion pass/fail details
├── failures.jsonl       # failed cases with failure signatures
├── clusters.json        # grouped failure clusters
├── summary.md           # human-readable run summary
└── repair_input.json    # export-ready repair suggestions
```

Options:

```bash
agent-eval run --config eval.yaml          # custom config path
agent-eval run --dataset cases/extra.jsonl # override dataset
agent-eval run --run-name baseline         # name this run
agent-eval run --concurrency 4             # parallel execution
```

### 4. Inspect & compare

```bash
# Inspect a specific run, case, or cluster
agent-eval inspect --run latest
agent-eval inspect --run latest --case pricing-query
agent-eval inspect --run latest --cluster c1

# Compare two runs (e.g. before/after a prompt change)
agent-eval compare --base baseline --target improved
agent-eval compare --base baseline --target improved --output comparison.json
agent-eval compare --base baseline --target improved --show
```

Comparison output includes:
- Pass-rate delta between runs
- Per-case transitions: `passed→failed`, `failed→passed`, unchanged
- Cluster transitions: added, removed, persisted failure groups

### 5. Export for tuning

```bash
agent-eval export --run latest
```

Produces `repair_input.json` with clustered failure evidence and suspected modules — ready for downstream prompt-tuning or code-fix pipelines.

## Target modes

### Script mode (default)

```yaml
project:
  mode: script
target:
  script:
    command: "{python} sample_agent.py --input-file {input_file}"
```

Your script receives a temp JSON file, prints JSON to stdout:

```json
{"response": {"answer": "..."}, "debug_meta": {"route": "knowledge_qa"}}
```

### HTTP mode

```yaml
project:
  mode: http
target:
  http:
    url: "http://localhost:8000/chat"
    method: "POST"
    headers:
      Content-Type: "application/json"
    payload_mapping:
      query: "$.inputs.query"
```

If the JSON response contains `debug_meta`, Agent-Eval uses it for execution-semantic checks; otherwise evaluation runs in black-box mode.

### Python adapter mode

```yaml
project:
  mode: adapter
target:
  adapter:
    module: my_agent_adapter
    function: run
```

Your adapter function is imported from the project root and receives the full case as a dictionary:

```python
def run(case: dict) -> dict:
    query = case["inputs"]["query"]
    return {
        "response": {"answer": f"answer for {query}"},
        "debug_meta": {"route": "knowledge_qa"},
    }
```

You may also return a raw response object directly, for black-box evaluation without `debug_meta`. Adapter mode is synchronous and in-process: a raised `TimeoutError` is recorded as a timeout result, but `runner.timeout_seconds` is not a hard cancellation mechanism for hung Python code in this MVP. If you run adapter cases concurrently, the adapter function must be thread-safe.

## Opt-in DeepEval judging

```bash
pip install -e '.[deepeval]'
```

```yaml
evaluation:
  llm_judge:
    enabled: true
    provider: deepeval
    model: gpt-4.1
    threshold: 0.7
```

## Release & verification

```bash
python scripts/check-release.py     # full gate: tests, build, twine, wheel smoke, e2e
python scripts/publish-release.py   # dry-run PyPI checks
python scripts/publish-release.py --publish  # upload to PyPI
```

## Non-goals

- No SaaS service or web dashboard
- No online observability / Langfuse dependency
- No automatic code patching or prompt modification
- No mandatory live LLM or DeepEval dependency
