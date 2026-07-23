"""BUY/SELL SIGNAL HTML must escape bare '<' from reason text (Telegram 400)."""
import html

from app.services.telegram_notifier import _escape_tg_html


def test_escape_tg_html_escapes_comparison_operators():
    raw = "RSI=40.8 < 30 (from config)"
    escaped = _escape_tg_html(raw)
    assert "<" not in escaped or "&lt;" in escaped
    assert escaped == html.escape(raw, quote=False)
    assert "&lt;" in escaped


def test_escape_tg_html_preserves_safe_text():
    assert _escape_tg_html("Intraday") == "Intraday"
    assert _escape_tg_html(None) == ""


def test_buy_signal_reason_with_lt_is_html_safe():
    """Simulate the exact Telegram-breaking payload seen in PROD TELEGRAM_FAILED rows."""
    reason = "RSI=40.8 < 30 (from config) | Price 1921.90 <= buy target 1930.00"
    safe = _escape_tg_html(reason)
    message = f"✅ Reason: {safe}"
    # Telegram treats bare "< " as Unsupported start tag ""
    assert "< " not in message
    assert "&lt;" in message
