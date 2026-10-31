"""Redact common sensitive fields and patterns in application logs."""

import re
from typing import Any

REDACTED = "[REDACTED]"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_JWT = re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_BEARER = re.compile(r"""(Bearer\s+)[^\s"'<>]+""", re.IGNORECASE)
_USERINFO = re.compile(r"([a-z][a-z0-9+.-]*://)[^/\s@]+@", re.IGNORECASE)
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----.*?"
    r"-----END [A-Z0-9 ]*PRIVATE KEY-----",
    re.DOTALL,
)


def _text(value: str) -> str:
    value = _PRIVATE_KEY.sub(REDACTED, value)
    value = _USERINFO.sub(lambda match: match.group(1) + REDACTED + "@", value)
    value = _BEARER.sub(lambda match: match.group(1) + REDACTED, value)
    value = _JWT.sub(REDACTED, value)
    return _EMAIL.sub(REDACTED, value)


def _sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]", "", key.lower())
    return (
        "password" in normalized
        or "secret" in normalized
        or "privatekey" in normalized
        or normalized in {
            "authorization", "proxyauthorization", "cookie", "setcookie",
            "token", "accesstoken", "refreshtoken", "idtoken", "apikey",
        }
    )


def _value(value: Any, depth: int = 0) -> Any:
    if depth > 20:
        return REDACTED
    if isinstance(value, dict):
        return {
            _text(str(key)): (
                REDACTED if _sensitive_key(str(key)) else _value(item, depth + 1)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_value(item, depth + 1) for item in value]
    if isinstance(value, str):
        return _text(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return _text(str(value))


def redact_log_event(_: Any, __: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    """Return a sanitized copy without changing the caller's objects."""
    return _value(event_dict)
