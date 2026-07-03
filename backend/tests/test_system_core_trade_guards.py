"""Tests for SYSTEM_CORE.md execution gates."""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.services import system_core_trade_guards as scg


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


class TestRsiGuard:
    def test_blocks_at_default_rsi_max(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_RSI_BUY_MAX", 40.0):
                with patch(
                    "app.services.order_position_service.count_open_positions_for_symbol",
                    return_value=0,
                ):
                    with patch(
                        "app.services.system_core_trade_guards.count_distinct_symbols_with_open_positions",
                        return_value=0,
                    ):
                        allowed, reason = scg.check_system_core_buy_allowed(
                            mock_db,
                            "ETH_USDT",
                            100.0,
                            rsi=42.0,
                            ma200=None,
                            price=3000.0,
                        )
        assert allowed is False
        assert "system_core_rsi" in reason
        assert "need_lt_40" in reason

    def test_allows_rsi_below_max(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_RSI_BUY_MAX", 50.0):
                with patch(
                    "app.services.order_position_service.count_open_positions_for_symbol",
                    return_value=0,
                ):
                    with patch(
                        "app.services.system_core_trade_guards.count_distinct_symbols_with_open_positions",
                        return_value=0,
                    ):
                        allowed, reason = scg.check_system_core_buy_allowed(
                            mock_db,
                            "ETH_USDT",
                            100.0,
                            rsi=45.0,
                            ma200=None,
                            price=3000.0,
                        )
        assert allowed is True
        assert reason == ""

    def test_rsi_max_env_default_is_40(self):
        with patch.dict(os.environ, {}, clear=False):
            assert float(os.getenv("SYSTEM_CORE_RSI_BUY_MAX", "40")) == 40.0


class TestOneActiveTradePerCoin:
    def test_blocks_when_material_position_exists(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch(
                "app.services.order_position_service.count_open_positions_for_symbol",
                return_value=1,
            ) as count_mock:
                allowed, reason = scg.check_system_core_buy_allowed(
                    mock_db,
                    "ETH_USDT",
                    100.0,
                    rsi=30.0,
                    ma200=None,
                    price=3000.0,
                )
        assert allowed is False
        assert reason == "system_core_one_active_trade_per_coin"
        count_mock.assert_called_once()
        kwargs = count_mock.call_args.kwargs
        assert kwargs["min_position_usd"] == scg._MIN_POSITION_USD
        assert kwargs["last_price"] == 3000.0

    def test_passes_dust_kwargs_from_env(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_MIN_POSITION_USD", 5.0):
                with patch.object(scg, "_MIN_POSITION_QTY", 0.05):
                    with patch(
                        "app.services.order_position_service.count_open_positions_for_symbol",
                        return_value=0,
                    ) as count_mock:
                        scg.check_system_core_buy_allowed(
                            mock_db,
                            "ETH_USDT",
                            100.0,
                            rsi=30.0,
                            ma200=None,
                            price=2500.0,
                        )
        kwargs = count_mock.call_args.kwargs
        assert kwargs["min_position_usd"] == 5.0
        assert kwargs["min_position_qty"] == 0.05
        assert kwargs["last_price"] == 2500.0


class TestGuardsDisabled:
    def test_skips_all_checks_when_disabled(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", False):
            allowed, reason = scg.check_system_core_buy_allowed(
                mock_db,
                "ETH_USDT",
                5000.0,
                rsi=99.0,
                ma200=1.0,
                price=0.5,
            )
        assert allowed is True
        assert reason == ""


class TestShortEntryGuard:
    """A short entry (margin SELL opening a NEW position) obeys the same exposure caps as a BUY,
    minus the BUY-only RSI/MA200 gates."""

    def test_allows_under_caps(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch(
                "app.services.order_position_service.count_open_positions_for_symbol",
                return_value=0,
            ):
                with patch(
                    "app.services.system_core_trade_guards.count_distinct_symbols_with_open_positions",
                    return_value=0,
                ):
                    allowed, reason = scg.check_system_core_short_entry_allowed(
                        mock_db, "DOT_USD", 100.0, price=6.0
                    )
        assert allowed is True
        assert reason == ""

    def test_blocks_one_active_trade_per_coin(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch(
                "app.services.order_position_service.count_open_positions_for_symbol",
                return_value=1,
            ):
                allowed, reason = scg.check_system_core_short_entry_allowed(
                    mock_db, "DOT_USD", 100.0, price=6.0
                )
        assert allowed is False
        assert reason == "system_core_one_active_trade_per_coin"

    def test_blocks_max_open_trades(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_resolve_max_open_trades", return_value=3):
                with patch(
                    "app.services.order_position_service.count_open_positions_for_symbol",
                    return_value=0,
                ):
                    with patch(
                        "app.services.system_core_trade_guards.count_distinct_symbols_with_open_positions",
                        return_value=3,
                    ):
                        allowed, reason = scg.check_system_core_short_entry_allowed(
                            mock_db, "DOT_USD", 100.0, price=6.0
                        )
        assert allowed is False
        assert "system_core_max_open_trades" in reason

    def test_blocks_amount_over_max_trade_usd(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_MAX_PER_TRADE", 1000.0):
                allowed, reason = scg.check_system_core_short_entry_allowed(
                    mock_db, "DOT_USD", 5000.0, price=6.0
                )
        assert allowed is False
        assert "system_core_max_trade_usd" in reason

    def test_skips_all_checks_when_disabled(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", False):
            allowed, reason = scg.check_system_core_short_entry_allowed(
                mock_db, "DOT_USD", 5000.0, price=6.0
            )
        assert allowed is True
        assert reason == ""
