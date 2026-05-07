from __future__ import annotations

from typing import Any


def get_path(data: Any, path: str | None, default: Any = None) -> Any:
    if not path or path == "$":
        return data
    if not path.startswith("$."):
        return default
    cur = data
    for part in path[2:].split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        elif isinstance(cur, list) and part.isdigit() and int(part) < len(cur):
            cur = cur[int(part)]
        else:
            return default
    return cur


def map_payload(case_inputs: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    source = {"inputs": case_inputs}
    for key, expr in mapping.items():
        if isinstance(expr, str) and expr.startswith("$.inputs."):
            value = get_path(source, expr, None)
            payload[key] = value
        elif isinstance(expr, str) and expr.startswith("$."):
            raise ValueError(f"Unsupported payload mapping expression: {expr}")
        else:
            payload[key] = expr
    return payload
