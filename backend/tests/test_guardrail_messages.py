"""Tests for guardrail reason humanization."""

from __future__ import annotations

from app.utils.decision_reason import ReasonCode
from app.utils.guardrail_messages import (
    humanize_guardrail_reason,
    order_failed_store_message,
    order_failed_telegram_error_section,
)


def test_one_active_trade_per_coin():
    msg = humanize_guardrail_reason("system_core_one_active_trade_per_coin", "AAVE_USDT")
    assert "AAVE" in msg
    assert "posición abierta" in msg


def test_max_open_trades():
    msg = humanize_guardrail_reason(
        "system_core_max_open_trades count=5 max=5",
        "BTC_USDT",
    )
    assert "máximo de posiciones abiertas" in msg


def test_max_trade_usd():
    msg = humanize_guardrail_reason(
        "system_core_max_trade_usd amount=1500 max=1000",
        "ETH_USDT",
    )
    assert "importe supera el máximo" in msg


def test_daily_drawdown():
    msg = humanize_guardrail_reason(
        "system_core_daily_drawdown dd_pct=6.00 peak=1000.00 now=940.00",
        "SOL_USDT",
    )
    assert "drawdown" in msg


def test_rsi():
    msg = humanize_guardrail_reason(
        "system_core_rsi rsi=45 need_lt_40",
        "DOT_USDT",
    )
    assert "RSI" in msg


def test_max_orders_per_symbol_per_day():
    msg = humanize_guardrail_reason(
        "blocked: MAX_ORDERS_PER_SYMBOL_PER_DAY limit reached (3/3)",
        "LINK_USDT",
    )
    assert "LINK" in msg
    assert "máximo de órdenes de hoy" in msg


def test_fallback_unknown_reason():
    raw = "system_core_ma200 price=1.0 ma200=2.0"
    msg = humanize_guardrail_reason(raw, "XRP_USDT")
    assert raw in msg


def test_order_failed_telegram_guardrail_includes_technical_detail():
    section, stored = order_failed_telegram_error_section(
        "system_core_one_active_trade_per_coin",
        "AAVE_USDT",
        ReasonCode.GUARDRAIL_BLOCKED.value,
    )
    assert "AAVE" in section
    assert "Detalle técnico: system_core_one_active_trade_per_coin" in section
    assert "posición abierta" in stored


def test_order_failed_telegram_non_guardrail_unchanged():
    section, stored = order_failed_telegram_error_section(
        "insufficient balance",
        "AAVE_USDT",
        ReasonCode.INSUFFICIENT_FUNDS.value,
    )
    assert section == "❌ Error: insufficient balance"
    assert stored == "insufficient balance"


def test_order_failed_store_message_guardrail_includes_tech():
    flat = order_failed_store_message(
        "AAVE_USDT",
        "BUY",
        "system_core_one_active_trade_per_coin",
        ReasonCode.GUARDRAIL_BLOCKED.value,
        display_reason="human text",
    )
    assert "human text" in flat
    assert "tech=system_core_one_active_trade_per_coin" in flat
