"""Unit tests for SIGNAL indicator persist / context merge."""

from __future__ import annotations

from app.utils.signal_indicators import (
    enrich_context_with_signal_indicators,
    merge_telegram_context,
    parse_indicators_from_message,
)


def test_parse_spaced_ma_and_rsi():
    got = parse_indicators_from_message(
        "SELL SIGNAL: AAVE_USD - MA50 90.27 < EMA10 91.33 | RSI=92.1 | Volume 2.21x"
    )
    assert got["rsi"] == 92.1
    assert got["ma50"] == 90.27
    assert got["ema10"] == 91.33
    assert got["volume_ratio"] == 2.21


def test_enrich_signal_message_adds_indicators():
    ctx = enrich_context_with_signal_indicators(
        message="✅ BUY SIGNAL: ETH_USD @ $1,900.0000 (N/A) - Auto | RSI=28.5, Price=1900, MA50=1890",
        throttle_reason=None,
        context=None,
    )
    assert ctx["rsi"] == 28.5
    assert ctx["ma50"] == 1890


def test_enrich_keeps_existing_keys():
    ctx = enrich_context_with_signal_indicators(
        message="BUY SIGNAL RSI=10",
        context={"rsi": 55.0, "symbol": "BTC_USD"},
    )
    assert ctx["rsi"] == 55.0
    assert ctx["symbol"] == "BTC_USD"


def test_merge_preserves_rsi_when_order_update():
    existing = {"rsi": 72.0, "ma50": 0.07, "symbol": "DOGE_USD"}
    incoming = {"symbol": "DOGE_USD", "order_id": "123", "exchange_order_id": "123"}
    merged = merge_telegram_context(existing, incoming)
    assert merged["rsi"] == 72.0
    assert merged["ma50"] == 0.07
    assert merged["order_id"] == "123"


def test_merge_from_json_string_existing():
    import json

    existing = json.dumps({"rsi": 40.0, "symbol": "X"})
    merged = merge_telegram_context(existing, {"order_id": "9"})
    assert merged["rsi"] == 40.0
    assert merged["order_id"] == "9"


def test_non_signal_message_unchanged():
    ctx = enrich_context_with_signal_indicators(
        message="✅ ORDER_CREATED: BTC_USD BUY - order_id=1",
        context={"order_id": "1"},
    )
    assert ctx == {"order_id": "1"}
    assert "rsi" not in ctx
