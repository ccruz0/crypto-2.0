"""Utility functions for redacting sensitive information from logs"""
import json
import re
from typing import Any, Dict, Iterable, Union


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
            # Redact sensitive fields
            if any(sensitive in key_lower for sensitive in ['secret', 'password', 'token', 'key', 'api_key', 'api_secret']):
                result[key] = "***REDACTED***"
            else:
                result[key] = redact_secrets(value, max_length)
        return result
    elif isinstance(data, list):
        return [redact_secrets(item, max_length) for item in data]
    elif isinstance(data, str):
        # Truncate long strings
        if len(data) > max_length:
            return data[:max_length] + "..."
        return data
    else:
        return data


# --- Telegram / ID masking helpers (log-safety) ---
# Lightweight and safe to import from any module.
# Avoids logging raw IDs and avoids logging raw Telegram API response bodies.


def mask_chat_id(value: Any, *, keep: int = 4) -> str:
    """
    Mask a Telegram chat/user ID for safe logging.

    Examples:
      123456789 -> "*****6789"
      -1001234567890 -> "-*********7890"
    """
    try:
        s = str(value) if value is not None else ""
    except Exception:
        return "(unprintable)"
    if not s:
        return "(empty)"

    sign = ""
    if s.startswith("-"):
        sign, s = "-", s[1:]

    if len(s) <= keep:
        return f"{sign}{'*' * len(s)}"

    return f"{sign}{'*' * (len(s) - keep)}{s[-keep:]}"


def mask_sequence_of_ids(values: Iterable[Any], *, keep: int = 4) -> str:
    """Mask a list/set of IDs for safe logging."""
    try:
        return ",".join(mask_chat_id(v, keep=keep) for v in values)
    except Exception:
        return "(unprintable)"


def _sanitize_telegram_value(value: Any) -> Any:
    """Recursively sanitize Telegram API payloads for logs."""
    sensitive_keys = {
        "chat_id",
        "from",
        "result",
        "message_id",
        "migrate_to_chat_id",
        "migrate_from_chat_id",
    }

    if isinstance(value, dict):
        out = {}
        for k, v in value.items():
            if str(k) in sensitive_keys:
                out[k] = "<redacted>"
            else:
                out[k] = _sanitize_telegram_value(v)
        return out

    if isinstance(value, list):
        return [_sanitize_telegram_value(v) for v in value]

    return value


def sanitize_telegram_api_response_for_log(data: Any, *, max_length: int = 200) -> str:
    """
    Safe, compact representation of Telegram API responses for logs.

    - dict/list: sanitize then JSON-dump and truncate
    - str/bytes: never log raw body; only log length
    """
    try:
        if isinstance(data, (bytes, bytearray)):
            return f"<body len={len(data)}>"

        if isinstance(data, str):
            return f"<body len={len(data)}>"

        if isinstance(data, (dict, list)):
            sanitized = _sanitize_telegram_value(data)
            s = json.dumps(sanitized, ensure_ascii=False)
            if len(s) > max_length:
                return s[:max_length] + "…"
            return s

        s = str(data)
        if len(s) > max_length:
            return s[:max_length] + "…"
        return s
    except Exception:
        return "<unloggable telegram response>"
