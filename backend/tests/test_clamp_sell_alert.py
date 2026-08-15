"""SELL / SHORT alerts are clamped off when the exchange disables margin sell."""

from unittest.mock import patch

from app.services.margin_info_service import clamp_sell_alert_enabled


@patch("app.services.margin_info_service.instrument_allows_margin_short", return_value=False)
def test_clamp_blocks_enabling_sell_alert_when_no_short(_mock):
    assert clamp_sell_alert_enabled("CRO_USD", True) is False
    assert clamp_sell_alert_enabled("CRO_USD", False) is False


@patch("app.services.margin_info_service.instrument_allows_margin_short", return_value=True)
def test_clamp_allows_sell_alert_when_short_ok(_mock):
    assert clamp_sell_alert_enabled("ETH_USD", True) is True
    assert clamp_sell_alert_enabled("ETH_USD", False) is False
