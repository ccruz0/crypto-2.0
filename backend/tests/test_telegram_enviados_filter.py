"""Enviados panel must match Telegram chat 1:1 (no phantom audit summaries)."""

from app.api.routes_monitoring import _is_phantom_telegram_audit_row, _infer_side_from_message


def test_phantom_summary_rows_are_excluded():
    assert _is_phantom_telegram_audit_row(
        "✅ BUY SIGNAL: AAVE_USD @ $93.6220 (-2.06%) - RSI oversold"
    )
    assert _is_phantom_telegram_audit_row(
        "🔴 SELL SIGNAL: DOT_USD @ $0.8082 (-5.20%) - Swing/Conservative"
    )
    assert _is_phantom_telegram_audit_row(
        "[DRY_RUN] BUY SIGNAL: BTC_USD @ $100.0000 (N/A) - test"
    )


def test_real_telegram_html_bodies_are_kept():
    assert not _is_phantom_telegram_audit_row(
        "🟢 <b>BUY SIGNAL DETECTED</b>\n\n📈 Symbol: <b>AAVE_USD</b>\n💵 Price: $93.6220"
    )
    assert not _is_phantom_telegram_audit_row(
        "🔴 <b>SELL SIGNAL DETECTED</b>\n\n📈 Symbol: <b>DOT_USD</b>"
    )
    assert not _is_phantom_telegram_audit_row(
        "🚫 <b>TRADE BLOCKED</b>\n\n📊 Symbol: <b>AAVE_USD</b>\n🔄 Side: BUY"
    )
    assert not _is_phantom_telegram_audit_row(
        "❌ ORDER_CANCELED: ALGO_USD BUY - order_id=123, status=REJECTED"
    )


def test_infer_side_for_ops_messages():
    assert _infer_side_from_message("ORDER_CANCELED: ALGO_USD BUY - order_id=1") == "BUY"
    assert _infer_side_from_message("🔴 <b>ORDER EXECUTED</b>\n📈 Side: SELL") == "SELL"
    assert _infer_side_from_message("🔧 ORPHAN / OCO HEALTH CHECK") == "UNKNOWN"
