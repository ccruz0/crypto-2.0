"""Regression: block margin short opens when exchange disables margin_sell.

Telegram 2026-08-08 CRO_USD: SELL signal → ORDER FAILED 608 CANNOT_SHORT_SELL_INSTRUMENT.
Public instruments: CRO_USD margin_buy_enabled=True, margin_sell_enabled=False.
"""

import asyncio
import os
import unittest
from unittest.mock import MagicMock, patch

from app.core.trading_invariants_week5 import REASON_SELL_REQUIRES_POSITION, validate_trading_decision
from app.services.margin_info_service import (
    MarginInfo,
    MarginInfoService,
    instrument_allows_margin_short,
)
from app.services.signal_monitor import SignalMonitorService


def _cro_usd_instrument():
    return {
        "symbol": "CRO_USD",
        "margin_buy_enabled": True,
        "margin_sell_enabled": False,
        "max_leverage": "50",
    }


def _eth_usd_instrument():
    return {
        "symbol": "ETH_USD",
        "margin_buy_enabled": True,
        "margin_sell_enabled": True,
        "max_leverage": "50",
    }


class TestMarginInfoSellFlag(unittest.TestCase):
    def setUp(self):
        self.svc = MarginInfoService()
        self.svc.clear_cache()

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_cro_buy_only_exposes_sell_false(self, mock_fetch):
        mock_fetch.return_value = [_cro_usd_instrument()]
        info = self.svc.get_margin_info_for_symbol("CRO_USD")
        self.assertTrue(info.margin_trading_enabled)
        self.assertTrue(info.margin_buy_enabled)
        self.assertFalse(info.margin_sell_enabled)

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_eth_allows_margin_short(self, mock_fetch):
        mock_fetch.return_value = [_eth_usd_instrument()]
        info = self.svc.get_margin_info_for_symbol("ETH_USD")
        self.assertTrue(info.margin_sell_enabled)
        self.assertTrue(instrument_allows_margin_short("ETH_USD"))

    @patch.object(MarginInfoService, "_fetch_all_instruments")
    def test_cro_denies_margin_short_helper(self, mock_fetch):
        mock_fetch.return_value = [_cro_usd_instrument()]
        self.assertFalse(instrument_allows_margin_short("CRO_USD"))


def _watchlist(*, trade_on_margin: bool):
    item = MagicMock()
    item.trade_amount_usd = 10.0
    item.trade_on_margin = trade_on_margin
    return item


async def _run_sell(*, symbol: str, trade_on_margin: bool, open_positions: int, env: dict, sell_ok: bool):
    svc = SignalMonitorService()
    db = MagicMock()
    captured: dict = {}

    def _validate(**kwargs):
        captured.update(kwargs)
        return validate_trading_decision(**kwargs)

    with patch.dict(os.environ, env, clear=False):
        with patch(
            "app.services.order_position_service.count_open_positions_for_symbol",
            return_value=open_positions,
        ):
            with patch(
                "app.core.trading_invariants_week5.validate_trading_decision",
                side_effect=_validate,
            ):
                with patch(
                    "app.services.margin_info_service.instrument_allows_margin_short",
                    return_value=sell_ok,
                ):
                    with patch("app.utils.live_trading.get_live_trading_status", return_value=False):
                        with patch(
                            "app.services.live_trading_gate.assert_exchange_mutation_allowed",
                        ):
                            with patch(
                                "app.services.signal_monitor.trade_client.place_market_order",
                                return_value={"order_id": "dry_sell_1", "status": "FILLED"},
                            ) as place:
                                result = await svc._place_order_from_signal(
                                    db,
                                    symbol,
                                    "SELL",
                                    _watchlist(trade_on_margin=trade_on_margin),
                                    0.05 if symbol.startswith("CRO") else 3000.0,
                                )
    return result, captured, place


def test_cro_short_blocked_when_margin_sell_disabled():
    result, captured, place = asyncio.run(
        _run_sell(
            symbol="CRO_USD",
            trade_on_margin=True,
            open_positions=0,
            env={"ALLOW_SHORTING": "true"},
            sell_ok=False,
        )
    )
    assert result.get("blocked") is True
    assert result.get("error") == "INSTRUMENT_SHORT_SELL_DISABLED"
    assert place.call_count == 0
    # Pre-block returns before week-5 invariants; no position_exists bypass.
    assert "position_exists" not in captured


def test_eth_short_still_allowed_when_margin_sell_enabled():
    result, captured, place = asyncio.run(
        _run_sell(
            symbol="ETH_USD",
            trade_on_margin=True,
            open_positions=0,
            env={"ALLOW_SHORTING": "true"},
            sell_ok=True,
        )
    )
    assert result.get("error") != REASON_SELL_REQUIRES_POSITION
    assert result.get("error") != "INSTRUMENT_SHORT_SELL_DISABLED"
    assert result.get("order_id") == "dry_sell_1"
    assert place.call_count == 1
    assert captured.get("position_exists") is True


def test_instrument_allows_margin_short_fail_closed_on_fetch_error():
    with patch(
        "app.services.margin_info_service.get_margin_info_for_symbol",
        side_effect=RuntimeError("boom"),
    ):
        assert instrument_allows_margin_short("CRO_USD") is False


def test_legacy_aggregated_flag_enables_both_sides():
    svc = MarginInfoService()
    svc.clear_cache()
    with patch.object(
        MarginInfoService,
        "_fetch_all_instruments",
        return_value=[{"symbol": "LEGACY_USD", "margin_trading_enabled": True, "max_leverage": "5"}],
    ):
        info = svc.get_margin_info_for_symbol("LEGACY_USD")
        assert isinstance(info, MarginInfo)
        assert info.margin_trading_enabled is True
        assert info.margin_buy_enabled is True
        assert info.margin_sell_enabled is True
