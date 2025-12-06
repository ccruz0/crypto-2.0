from types import SimpleNamespace

from app.services.telegram_commands import _format_coin_status_icons, _format_coin_summary


def _make_item(**overrides):
    defaults = dict(
        symbol="BTC_USDT",
        alert_enabled=True,
        trade_enabled=False,
        trade_on_margin=True,
        trade_amount_usd=150.0,
        sl_tp_mode="aggressive",
        min_price_change_pct=1.25,
        sl_percentage=4.5,
        tp_percentage=9.0,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_format_coin_status_icons_shows_three_flags():
    item = _make_item(alert_enabled=True, trade_enabled=True, trade_on_margin=False)
    icons = _format_coin_status_icons(item)
    assert "🔔" in icons
    assert "🤖" in icons
    assert "💤" in icons  # margin off


def test_format_coin_summary_includes_key_fields():
    item = _make_item()
    summary = _format_coin_summary(item)
    assert "BTC_USDT" not in summary  # summary only contains fields, not the title
    assert "ENABLED" in summary  # alert enabled text
    assert "DISABLED" in summary  # trade disabled text
    assert "$150.00" in summary
    assert "Aggressive" in summary
    assert "1.25%" in summary


