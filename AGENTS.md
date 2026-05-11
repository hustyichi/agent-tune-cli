# Repository Guidelines

## Project Structure & Module Organization

This repository publishes the Python package `agent-deepeval` and installs the `agent-eval` CLI. Source code lives in `agent_eval/`; CLI entry points are in `agent_eval/cli.py`, with feature modules such as `artifacts.py`, `comparison.py`, `clustering.py`, and `reporting.py`. Package templates are under `agent_eval/templates/`. Tests live in `tests/` and should mirror user-facing behavior, especially CLI flows. Product and release docs live in `docs/`; release automation lives in `scripts/`. Build outputs (`build/`, `dist/`, `*.egg-info`) are generated and ignored.

## Build, Test, and Development Commands

```bash
python3 -m pip install -e '.[dev,release]'  # install editable package plus test/release tools
python -m ruff format .                     # format Python code with the canonical Ruff formatter
python -m ruff format --check .             # verify Python formatting without rewriting files
pytest                                      # run the full test suite
python -m compileall -q agent_eval tests    # quick syntax/import sanity check
python scripts/check-release.py             # full release gate: tests, build, twine check, wheel smoke, fresh CLI e2e
python scripts/publish-release.py           # dry-run official PyPI release checks
python scripts/publish-release.py --publish # upload current version to official PyPI
```

Use `agent-eval --help` and a temporary project with `agent-eval init && agent-eval run` for manual smoke testing.

## Coding Style & Naming Conventions

Target Python 3.10+. Ruff is the canonical Python formatter for this repository; run `python -m ruff format .` before committing and use the checked-in `pyproject.toml` Ruff settings rather than another formatter. Use 4-space indentation, type hints where they clarify interfaces, and small functions with explicit error messages. Keep CLI command names kebab-case (`agent-eval compare`) and Python names snake_case. Preserve public artifact names and protocol values such as `agent-eval/v1alpha1` unless a migration plan updates tests and docs together.

## Testing Guidelines

Pytest is the test framework; `pyproject.toml` sets `tests/` as the test path and quiet output. Name tests `test_*.py` and test functions `test_<behavior>`. Add or update tests before changing CLI behavior, artifact contracts, release gates, or packaging metadata. Release-sensitive changes must pass `python scripts/check-release.py` before merge.

## Commit & Pull Request Guidelines

Recent history uses concise intent-first subjects, sometimes with Conventional Commit scopes (for example, `fix(check-release): ...`). Commits should follow the repository Lore style: explain why, then include useful trailers such as `Constraint:`, `Rejected:`, `Confidence:`, `Scope-risk:`, `Directive:`, `Tested:`, and `Not-tested:`. PRs should state the user-visible change, list verification commands run, note release or artifact-contract risks, and link related issues or planning docs when available.

## Security & Configuration Tips

Do not commit credentials, API keys, or PyPI tokens. The publish script expects Twine credentials from the caller’s environment. Default workflows should remain local-first and offline; optional DeepEval/live LLM behavior must stay opt-in.
