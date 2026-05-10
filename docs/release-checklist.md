# Release Checklist

This checklist is the release gate for publishing the project as the PyPI
distribution `agent-deepeval`. The installed console command remains
`agent-eval`.

## Release identity

- PyPI distribution: `agent-deepeval`
- Console script: `agent-eval`
- Import package: `agent_eval`
- Protocol version: `agent-eval/v1alpha1`

Before any upload, re-check the official PyPI package and version state. If the
name or version is unavailable, stop and ask for a user decision; do not rename
or bump the version silently.

## Supported MVP surface

The release covers the current local-first MVP commands:

- `agent-eval init`
- `agent-eval run`
- `agent-eval inspect`
- `agent-eval compare`
- `agent-eval export`

Default generated projects must run offline. The default LLM judge behavior is
stubbed/disabled and must not require API keys, SaaS, online observability, a
database, or live LLM calls.

## Deferred features / non-goals

The release must not claim or implement these deferred capabilities:

- local adapter mode
- live LLM or DeepEval provider expansion beyond the existing optional path
- LLM cluster summary / naming
- full deep report
- SaaS, Web Dashboard, online observability, or database
- automatic code patching, prompt modification, or PR creation
- breaking changes to current artifact filenames or core protocol shape

## Local release gate

Run the source-of-truth local gate:

```bash
python scripts/check-release.py
```

The script must verify:

1. `python -m pytest -q`
2. `python -m compileall -q agent_eval tests`
3. wheel and sdist build into a temporary dist directory
4. `python -m twine check <temp-dist>/*`
5. wheel install into a temporary virtual environment
6. installed `agent-eval --help`
7. fresh-project `agent-eval init`
8. fresh-project `agent-eval run`
9. fresh-project `agent-eval inspect --run latest`
10. fresh-project `agent-eval export --run latest`
11. fresh-project `agent-eval compare --base latest --target latest`
12. required run artifacts:
    - `runs/latest.txt`
    - `reports/latest.md`
    - `manifest.json`
    - `raw_results.jsonl`
    - `eval_results.jsonl`
    - `failures.jsonl`
    - `clusters.json`
    - `summary.md`
    - `repair_input.json`

Do not publish if this gate fails.

## Stale-name gate

Run a repo-wide search before publishing. No non-historical source, docs,
metadata, lockfile, test, script, CI, or runtime/user-facing message should
refer to the old distribution name. Historical `.omx` planning artifacts may
retain old-name evidence when clearly historical.

`uv.lock` is maintained in this repository and must be regenerated or updated
when package metadata changes.

## TestPyPI gate

TestPyPI requires credentials or trusted publishing. If credentials are
unavailable, stop with the exact pending commands and do not claim TestPyPI
completion.

Suggested flow after the local gate:

```bash
rm -rf dist
python -m build --sdist --wheel --outdir dist
python -m twine check dist/*
python -m twine upload --repository testpypi dist/*
```

Install verification should avoid dependency confusion between TestPyPI and
PyPI. Prefer installing the local wheel first to populate runtime dependencies,
then replacing only the project package from TestPyPI:

```bash
python -m venv /tmp/agent-deepeval-testpypi
/tmp/agent-deepeval-testpypi/bin/python -m pip install dist/agent_deepeval-0.1.0-py3-none-any.whl
/tmp/agent-deepeval-testpypi/bin/python -m pip uninstall -y agent-deepeval
/tmp/agent-deepeval-testpypi/bin/python -m pip install --index-url https://test.pypi.org/simple/ --no-deps agent-deepeval==0.1.0
/tmp/agent-deepeval-testpypi/bin/agent-eval --help
```

If TestPyPI already has the target version, stop and ask; do not auto-bump.

## PyPI gate

Before real PyPI upload:

1. Re-run `python scripts/check-release.py`.
2. Re-check official PyPI name/version availability for `agent-deepeval`.
3. Build a clean `dist/`.
4. Run `python -m twine check dist/*`.
5. Upload only with valid credentials or trusted publishing.

```bash
python -m twine upload dist/*
```

After upload, verify from a clean environment:

```bash
python -m venv /tmp/agent-deepeval-pypi
/tmp/agent-deepeval-pypi/bin/python -m pip install agent-deepeval
/tmp/agent-deepeval-pypi/bin/agent-eval --help
```

If publishing fails because of credentials, name reservation, version conflict,
or package-index policy, stop with evidence and the pending command. Do not
claim release completion.

