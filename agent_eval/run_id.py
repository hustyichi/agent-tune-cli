from __future__ import annotations

import re
from datetime import datetime

RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


def new_run_id(name: str | None = None) -> str:
    if name:
        if (
            not RUN_ID_RE.fullmatch(name)
            or name in {".", ".."}
            or "/" in name
            or "\\" in name
        ):
            raise ValueError(
                "run name must use only letters, numbers, dot, dash, and underscore; path separators are not allowed"
            )
        return name
    return datetime.now().strftime("%Y-%m-%d_%H%M%S")
