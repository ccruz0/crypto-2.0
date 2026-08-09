"""Parse + merge indicator fields for telegram_messages.context_json.

Prod SIGNAL rows historically stored only order ids in context after decision
trace updates; RSI/MA lived in message/reason text. Persist parseable
indicators at write time and merge (not replace) on decision-trace updates.
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional


def _parse_float_token(raw: str) -> Optional[float]:
    text = (raw or "").strip().replace(",", "")
    if not text or text.upper() in ("N/A", "NA", "NONE", "-"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_indicators_from_message(message: str) -> dict[str, float]:
    """Pull RSI/MA/ATR/volume from SIGNAL reason / message body."""
    if not message:
        return {}
    out: dict[str, float] = {}
    patterns = (
        ("rsi", r"RSI\s*[=:]\s*([^\s,|<]+)"),
        ("ma50", r"MA50\s*[=:]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"),
        ("ma200", r"MA200\s*[=:]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"),
        ("ema10", r"EMA10\s*[=:]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)"),
        ("atr", r"ATR(?:14)?\s*[=:]\s*([^\s,|]+)"),
        ("price", r"Price\s*[=:]\s*\$?\s*([^\s,|]+)"),
        ("volume_ratio", r"Vol(?:ume)?\s*[=:]?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*x"),
    )
    for key, pat in patterns:
        m = re.search(pat, message, flags=re.IGNORECASE)
        if not m:
            continue
        val = _parse_float_token(m.group(1))
        if val is not None:
            out[key] = val
    return out


def coerce_context_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode("utf-8", errors="ignore")
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return {}
        try:
            data = json.loads(text)
            return dict(data) if isinstance(data, dict) else {}
        except Exception:
            return {}
    return {}


def message_looks_like_signal(message: str) -> bool:
    text = message or ""
    upper = text.upper()
    return (
        "BUY SIGNAL" in upper
        or "SELL SIGNAL" in upper
        or "🟢" in text
        or "🔴" in text
    )


def enrich_context_with_signal_indicators(
    *,
    message: str,
    throttle_reason: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Merge parsed indicators into context (existing keys win over parse)."""
    out = coerce_context_dict(context)
    if not message_looks_like_signal(message) and not message_looks_like_signal(
        throttle_reason or ""
    ):
        return out
    parsed: dict[str, float] = {}
    parsed.update(parse_indicators_from_message(message or ""))
    parsed.update(parse_indicators_from_message(throttle_reason or ""))
    for key, val in parsed.items():
        if key not in out or out.get(key) is None:
            out[key] = val
    return out


def merge_telegram_context(
    existing: Any,
    incoming: Optional[dict[str, Any]],
) -> dict[str, Any]:
    """Merge decision-trace context onto existing row context (preserve RSI/MA)."""
    base = coerce_context_dict(existing)
    new = coerce_context_dict(incoming)
    merged = dict(base)
    merged.update(new)
    return merged
