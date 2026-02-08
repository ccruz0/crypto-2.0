"""
Pipeline logging helpers for no-silent-failure contract.
Provides JSON-serializable payloads and a consistent critical-failure log format.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


def make_json_safe(obj: Any) -> Any:
    """
    Convert a value to a JSON-serializable form.
    - Decimal -> float (via str to avoid precision issues, then float)
    - datetime -> ISO string
    - UUID / str(id(x))-like -> str
    - dict -> recursively make_json_safe values
    - list -> recursively make_json_safe elements
    - None, bool, int, float, str -> return as-is
    """
    if obj is None or isinstance(obj, (bool, int, float, str)):
        return obj
    if isinstance(obj, Decimal):
        return float(str(obj))
    if isinstance(obj, datetime):
        return obj.isoformat() if hasattr(obj, "isoformat") else str(obj)
    if hasattr(obj, "hex") and callable(getattr(obj, "hex", None)):
        return str(obj)  # UUID-like
    if isinstance(obj, dict):
        return {k: make_json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [make_json_safe(v) for v in obj]
    return str(obj)


def format_critical_failure(
    correlation_id: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    order_id: Optional[str] = None,
    error_code: Optional[str] = None,
    message: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Build a structured payload for critical failure logging.
    All fields are optional; only non-None are included.
    Result is JSON-serializable and safe for single-line logger.info(json.dumps(...)).
    """
    payload: Dict[str, Any] = {"event": "CRITICAL_FAILURE"}
    if correlation_id is not None:
        payload["correlation_id"] = str(correlation_id)
    if symbol is not None:
        payload["symbol"] = str(symbol)
    if side is not None:
        payload["side"] = str(side)
    if order_id is not None:
        payload["order_id"] = str(order_id)
    if error_code is not None:
        payload["error_code"] = str(error_code)
    if message is not None:
        payload["message"] = str(message)[:500]
    return payload


def log_critical_failure(
    correlation_id: Optional[str] = None,
    symbol: Optional[str] = None,
    side: Optional[str] = None,
    order_id: Optional[str] = None,
    error_code: Optional[str] = None,
    message: Optional[str] = None,
) -> None:
    """Log a single-line critical failure with structured payload (no secrets)."""
    payload = format_critical_failure(
        correlation_id=correlation_id,
        symbol=symbol,
        side=side,
        order_id=order_id,
        error_code=error_code,
        message=message,
    )
    logger.error("[PIPELINE_FAILURE] %s", json.dumps(payload))
