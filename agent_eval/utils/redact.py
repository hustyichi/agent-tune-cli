from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEYS = {
    "authorization", "cookie", "set-cookie", "api_key", "apikey", "api-key",
    "token", "access_token", "refresh_token", "password", "secret", "client_secret",
    "prompt", "full_prompt", "context_full", "intermediate_context",
}
REDACTED = "[REDACTED]"
SECRET_PATTERN = re.compile(r"[A-Za-z0-9_.:-]*(?:SECRET|TOKEN|API[_-]?KEY|PASSWORD)[A-Za-z0-9_.:=/-]*", re.IGNORECASE)
SECRET_VALUE_PATTERN = re.compile(r"(?i)\b(?:sk|pk|rk|api|token|secret|key|bearer)[-_][A-Za-z0-9][A-Za-z0-9_.=-]{5,}\b")
FLAG_VALUE_PATTERN = re.compile(r"(?i)(--(?:api-?key|token|password|secret|authorization)\s+)(\S+)")
BEARER_VALUE_PATTERN = re.compile(r"(?i)(bearer\s+)(\S+)")


def is_sensitive_key(key: str) -> bool:
    lower = key.lower().replace("-", "_")
    return lower in SENSITIVE_KEYS or any(marker in lower for marker in ("api_key", "token", "password", "secret"))


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: (REDACTED if is_sensitive_key(str(k)) else redact(v)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def redact_text(value: str | None) -> str | None:
    if value is None:
        return None
    redacted = FLAG_VALUE_PATTERN.sub(lambda m: m.group(1) + REDACTED, value)
    redacted = BEARER_VALUE_PATTERN.sub(lambda m: m.group(1) + REDACTED, redacted)
    redacted = SECRET_VALUE_PATTERN.sub(REDACTED, redacted)
    return SECRET_PATTERN.sub(REDACTED, redacted)
