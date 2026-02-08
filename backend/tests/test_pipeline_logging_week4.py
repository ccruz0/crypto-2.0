"""
Week 4: Pipeline logging and no-silent-failure contract.
Tests for make_json_safe, format_critical_failure, and JSON-serializable audit payloads.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from app.utils.pipeline_logging import (
    format_critical_failure,
    make_json_safe,
)


class TestMakeJsonSafe:
    """make_json_safe must produce JSON-serializable values."""

    def test_decimal_to_float(self):
        val = make_json_safe(Decimal("5.10"))
        assert isinstance(val, float)
        assert val == 5.10
        json.dumps(val)

    def test_datetime_to_iso_string(self):
        dt = datetime(2025, 2, 8, 12, 0, 0, tzinfo=timezone.utc)
        val = make_json_safe(dt)
        assert isinstance(val, str)
        assert "2025-02-08" in val
        json.dumps(val)

    def test_uuid_like_to_str(self):
        u = uuid.uuid4()
        val = make_json_safe(u)
        assert isinstance(val, str)
        json.dumps(val)

    def test_dict_recursive(self):
        payload = {
            "a": Decimal("1.5"),
            "b": datetime(2025, 1, 1, tzinfo=timezone.utc),
            "c": "ok",
        }
        out = make_json_safe(payload)
        assert json.dumps(out)  # no TypeError
        assert isinstance(out["a"], float)
        assert isinstance(out["b"], str)
        assert out["c"] == "ok"

    def test_audit_log_like_payload_serializable(self):
        """Audit log with Decimal, datetime, UUID-like must serialize."""
        audit = {
            "event": "ORDER_EXECUTED_NOTIFICATION",
            "symbol": "DOT_USDT",
            "order_id": "12345",
            "delta_quantity": float(Decimal("0.24")),
            "avg_price": Decimal("5.10"),
            "trade_signal_id": 42,
            "client_oid": str(uuid.uuid4()),
        }
        safe = make_json_safe(audit)
        s = json.dumps(safe)
        assert "DOT_USDT" in s
        assert "0.24" in s or 0.24 in (safe["delta_quantity"],)


class TestFormatCriticalFailure:
    """format_critical_failure must include correlation_id and be JSON-serializable."""

    def test_contains_correlation_id(self):
        payload = format_critical_failure(
            correlation_id="a1b2c3d4",
            symbol="ETH_USDT",
            side="BUY",
            order_id="ord-1",
            error_code="SYNC_ORDER_HISTORY",
            message="test error",
        )
        assert payload["event"] == "CRITICAL_FAILURE"
        assert payload["correlation_id"] == "a1b2c3d4"
        assert payload["symbol"] == "ETH_USDT"
        assert payload["side"] == "BUY"
        assert payload["order_id"] == "ord-1"
        assert payload["error_code"] == "SYNC_ORDER_HISTORY"
        assert payload["message"] == "test error"
        json.dumps(payload)

    def test_optional_fields_omitted(self):
        payload = format_critical_failure(message="only message")
        assert "message" in payload
        assert "correlation_id" not in payload
        assert "symbol" not in payload
        json.dumps(payload)

    def test_used_in_log_payload_generation(self):
        """Correlation ID is accepted and appears in the formatter output for logs."""
        payload = format_critical_failure(
            correlation_id="e2e-123",
            symbol="DOT_USDT",
            side="SELL",
            order_id=None,
            error_code="ORDER_PLACEMENT",
            message="Exchange rejected",
        )
        assert payload["correlation_id"] == "e2e-123"
        line = json.dumps(payload)
        assert "e2e-123" in line
        assert "DOT_USDT" in line
        assert "ORDER_PLACEMENT" in line
