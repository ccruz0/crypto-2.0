"""Tests for daily-summary rollup of non-executed orders."""

from collections import defaultdict
from types import SimpleNamespace

from app.services.daily_summary import DailySummaryService


def test_bucket_key_collapses_max_open_orders_counters():
    row_a = SimpleNamespace(
        reason_code="GUARDRAIL_BLOCKED",
        throttle_reason="blocked: MAX_OPEN_ORDERS_TOTAL limit reached (27/10)",
        reason_message=None,
    )
    row_b = SimpleNamespace(
        reason_code="GUARDRAIL_BLOCKED",
        throttle_reason="blocked: MAX_OPEN_ORDERS_TOTAL limit reached (28/10)",
        reason_message=None,
    )
    key_a, label_a = DailySummaryService._non_executed_bucket_key(row_a)
    key_b, label_b = DailySummaryService._non_executed_bucket_key(row_b)
    assert key_a == key_b == "MAX_OPEN_ORDERS_TOTAL"
    assert "Tope global" in label_a
    assert label_a == label_b


def test_bucket_key_amount_usd():
    row = SimpleNamespace(
        reason_code="INVALID_TRADE_AMOUNT",
        throttle_reason=None,
        reason_message="Amount USD not configured for ETH_USD",
    )
    key, label = DailySummaryService._non_executed_bucket_key(row)
    assert key == "INVALID_TRADE_AMOUNT"
    assert "Amount USD" in label


def test_format_non_executed_orders_summary_empty():
    svc = DailySummaryService()
    text = svc.format_non_executed_orders_summary(
        {"hours": 24, "total_events": 0, "unique_symbols": 0, "buckets": []}
    )
    assert "Órdenes no ejecutadas" in text
    assert "Ningún intento" in text


def test_format_non_executed_orders_summary_groups():
    svc = DailySummaryService()
    text = svc.format_non_executed_orders_summary(
        {
            "hours": 24,
            "total_events": 12,
            "unique_symbols": 2,
            "buckets": [
                {
                    "key": "MAX_OPEN_ORDERS_TOTAL",
                    "label": "Tope global de órdenes abiertas",
                    "count": 10,
                    "symbols": defaultdict(int, {"ETH_USDT": 6, "DOT_USD": 4}),
                    "decision_types": defaultdict(int, {"SKIPPED": 10}),
                },
                {
                    "key": "INVALID_TRADE_AMOUNT",
                    "label": "Amount USD no configurado",
                    "count": 2,
                    "symbols": defaultdict(int, {"ETH_USD": 2}),
                    "decision_types": defaultdict(int, {"SKIPPED": 2}),
                },
            ],
        }
    )
    assert "12 intento" in text
    assert "Tope global de órdenes abiertas — 10×" in text
    assert "ETH_USDT" in text
    assert "Amount USD no configurado — 2×" in text
