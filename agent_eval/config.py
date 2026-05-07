from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .models import EvalConfig


def load_config(path: str | Path = "eval.yaml") -> EvalConfig:
    p = Path(path)
    data: dict[str, Any] = {}
    if p.exists():
        data = yaml.safe_load(p.read_text()) or {}
    return EvalConfig.model_validate(data)


def dump_config(config: EvalConfig) -> dict[str, Any]:
    return config.model_dump(mode="json")
