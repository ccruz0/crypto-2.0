"""Tests for guardrail reason humanization (supersedes conflicted PR #102 wiring)."""

from __future__ import annotations

from app.utils.decision_reason import ReasonCode, format_order_failed_telegram
from app.utils.guardrail_messages import (
    humanize_guardrail_reason,
    order_failed_store_message,
    order_failed_telegram_error_section,
)


def test_one_active_trade_per_coin():
    msg = humanize_guardrail_reason("system_core_one_active_trade_per_coin", "AAVE_USDT")
    assert "AAVE" in msg
    assert "posición abierta" in msg
    assert "Compra" in msg


def test_sell_side_wording():
    msg = humanize_guardrail_reason(
        "system_core_one_active_trade_per_coin",
        "AAVE_USDT",
        side="SELL",
    )
    assert "Venta" in msg


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


def test_ma200():
    msg = humanize_guardrail_reason(
        "system_core_ma200 price=1.0 ma200=2.0",
        "XRP_USDT",
    )
    assert "MA200" in msg


def test_max_orders_per_symbol_per_day():
    msg = humanize_guardrail_reason(
        "blocked: MAX_ORDERS_PER_SYMBOL_PER_DAY limit reached (3/3)",
        "LINK_USDT",
    )
    assert "LINK" in msg
    assert "máximo de órdenes de hoy" in msg


def test_fallback_unknown_reason():
    raw = "system_core_unknown_widget"
    msg = humanize_guardrail_reason(raw, "XRP_USDT")
    assert raw in msg


def test_instrument_short_sell_disabled_does_not_sound_like_watchlist_off():
    msg = humanize_guardrail_reason(
        "Watchlist Margin YES is on for CRO_USD, but Crypto.com does not "
        "allow opening a SHORT (margin_sell_enabled=false).",
        "CRO_USD",
        side="SELL",
    )
    assert "Venta" in msg
    assert "CRO" in msg
    assert "Margin YES" in msg
    assert "SHORT" in msg
    assert "watchlist" in msg.lower()


def test_order_failed_telegram_guardrail_includes_technical_detail():
    section, stored = order_failed_telegram_error_section(
        "system_core_one_active_trade_per_coin",
        "AAVE_USDT",
        ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value,
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
        ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value,
        display_reason="human text",
    )
    assert "human text" in flat
    assert "tech=system_core_one_active_trade_per_coin" in flat


def test_format_order_failed_telegram_uses_humanized_error_line():
    text = format_order_failed_telegram(
        symbol="BTC_USD",
        side="BUY",
        error_msg="system_core_one_active_trade_per_coin",
        reason_code=ReasonCode.ONE_ACTIVE_TRADE_PER_COIN.value,
    )
    assert "posición abierta" in text
    assert "Detalle técnico: system_core_one_active_trade_per_coin" in text
    assert "Máx. 1 trade activo" in text
    assert "❌ Error: system_core_one_active_trade_per_coin" not in text
