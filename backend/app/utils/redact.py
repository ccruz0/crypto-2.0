"""Utility functions for redacting sensitive information from logs.

Use these helpers in all hot paths: Crypto.com client, Telegram notifier,
order placement/cancel/sync. Never log API keys, secrets, bot tokens,
Authorization headers, or full chat IDs.
"""
from typing import Any, Dict, List, Optional, Union

# Keys that must be redacted in headers or dicts
_SENSITIVE_HEADER_KEYS = frozenset(
    k.lower()
    for k in (
        "authorization",
        "x-api-key",
        "api-key",
        "x-auth-token",
        "cookie",
        "proxy-authorization",
    )
)


def mask_token(s: Optional[str], first: int = 6, last: int = 6) -> str:
    """Mask a token (API key, bot token, etc.): keep first N + last N, redact middle.

    Never log the full token. Use for API keys, bearer tokens, bot tokens.
    """
    if not s or not isinstance(s, str):
        return "<NOT_SET>"
    s = s.strip()
    if len(s) <= first + last:
        return "***"
    return s[:first] + "..." + s[-last:]


def mask_chat_id(s: Optional[Union[str, int]], keep_last: int = 4) -> str:
    """Mask a chat ID: keep last N digits only (e.g. for correlation)."""
    if s is None:
        return "<NOT_SET>"
    t = str(s).strip()
    if not t or not t.replace("-", "").isdigit():
        return "***"
    if len(t) <= keep_last:
        return "***"
    return "*" * (len(t) - keep_last) + t[-keep_last:]


def redact_headers(headers: Optional[Dict[str, str]]) -> Dict[str, str]:
    """Return a copy of headers with Authorization and other sensitive keys redacted."""
    if not headers:
        return {}
    out = {}
    for k, v in headers.items():
        key_lower = k.lower()
        if key_lower in _SENSITIVE_HEADER_KEYS or "auth" in key_lower or "token" in key_lower:
            out[k] = "<REDACTED>"
        else:
            out[k] = v
    return out


def safe_str(obj: Any, max_length: int = 200) -> str:
    """Best-effort safe serialization for logging. Never dumps env or full credentials."""
    if obj is None:
        return "None"
    if isinstance(obj, (bool, int, float)):
        return str(obj)
    if isinstance(obj, str):
        if len(obj) > max_length:
            return obj[:max_length] + "..."
        return obj
    if isinstance(obj, dict):
        return "<dict keys=" + ",".join(str(k) for k in list(obj.keys())[:10]) + ">"
    if isinstance(obj, (list, tuple)):
        return f"<{type(obj).__name__} len={len(obj)}>"
    return type(obj).__name__ + "()"


def mask_sequence_of_ids(ids: Optional[List[Union[str, int]]], keep_last: int = 4) -> str:
    """Mask a list of IDs (e.g. authorized chat IDs) for logging."""
    if not ids:
        return "none"
    masked = [mask_chat_id(x, keep_last) for x in ids[:20]]
    if len(ids) > 20:
        masked.append("...")
    return ",".join(masked)


# Keys in Telegram API responses that may contain identifiers (never log raw)
_TELEGRAM_REDACT_KEYS = frozenset(
    k.lower()
    for k in (
        "chat_id",
        "from",
        "result",
        "message_id",
        "migrate_to_chat_id",
        "migrate_from_chat_id",
    )
)


def _sanitize_telegram_value(value: Any) -> Any:
    """Recursive sanitizer: returns sanitized structure (dict/list/other)."""
    if value is None:
        return None
    if isinstance(value, dict):
        return {
            k: "<REDACTED>" if str(k).lower() in _TELEGRAM_REDACT_KEYS else _sanitize_telegram_value(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [_sanitize_telegram_value(x) for x in value[:5]]
    return value


def sanitize_telegram_api_response_for_log(data: Any, max_length: int = 200) -> str:
    """Sanitize Telegram API response/error for logging. No raw chat_id, from, or result body."""
    if data is None:
        return "None"
    if isinstance(data, str):
        return f"<body len={len(data)}>"
    if isinstance(data, dict):
        import json
        sanitized = _sanitize_telegram_value(data)
        s = json.dumps(sanitized, default=str)
        return s[:max_length] + "..." if len(s) > max_length else s
    return str(data)[:max_length]


def redact_secrets(data: Any, max_length: int = 100) -> Any:
    """
    Redact sensitive information from data to prevent logging secrets.

    Args:
        data: The data to redact (dict, list, str, etc.)
        max_length: Maximum length of string values before truncation

    Returns:
        Data with sensitive fields redacted
    """
    if isinstance(data, dict):
        result = {}
        for key, value in data.items():
            key_lower = str(key).lower()
            if any(
                s in key_lower
                for s in (
                    "secret",
                    "password",
                    "token",
                    "api_key",
                    "api_secret",
                    "bearer",
                    "authorization",
                )
            ):
                result[key] = "***REDACTED***"
            else:
                result[key] = redact_secrets(value, max_length)
        return result
    if isinstance(data, list):
        return [redact_secrets(item, max_length) for item in data]
    if isinstance(data, str):
        if len(data) > max_length:
            return data[:max_length] + "..."
        return data
    return data
