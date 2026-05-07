from __future__ import annotations

from pathlib import Path

from agent_eval.artifacts import resolve_run


def export_repair_input(root: Path, run: str) -> str:
    run_dir = resolve_run(root, run)
    path = run_dir / "repair_input.json"
    if not path.exists():
        raise FileNotFoundError(f"repair_input.json not found for run {run}")
    return str(path)
