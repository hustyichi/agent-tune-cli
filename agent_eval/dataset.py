from __future__ import annotations

import json
from pathlib import Path

from .models import EvalCase


def load_cases(paths: list[str], root: Path | str = ".") -> list[EvalCase]:
    root_path = Path(root)
    cases: list[EvalCase] = []
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        if not path.is_absolute():
            path = root_path / path
        with path.open() as fh:
            for lineno, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    data = json.loads(line)
                    case = EvalCase.model_validate(data)
                except Exception as exc:  # noqa: BLE001 - include line context
                    raise ValueError(f"Invalid case at {path}:{lineno}: {exc}") from exc
                if case.id in seen:
                    raise ValueError(f"Duplicate case id: {case.id}")
                seen.add(case.id)
                cases.append(case)
    return cases
