"""Tests for trading limits config resolution and system_core guard wiring."""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.services import system_core_trade_guards as scg
from app.services.config_loader import get_trading_limits


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


class TestGetTradingLimits:
    def test_defaults_when_config_empty(self):
        with patch("app.services.config_loader.load_config", return_value={}):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("SYSTEM_CORE_MAX_OPEN_TRADES", None)
                os.environ.pop("SYSTEM_CORE_MAX_OPEN_PER_COIN", None)
                limits = get_trading_limits()
        assert limits == {"maxOpenOrdersTotal": 5, "maxOpenOrdersPerCoin": 1}

    def test_config_overrides_env(self):
        with patch(
            "app.services.config_loader.load_config",
            return_value={"trading_limits": {"maxOpenOrdersTotal": 8, "maxOpenOrdersPerCoin": 2}},
        ):
            with patch.dict(os.environ, {"SYSTEM_CORE_MAX_OPEN_TRADES": "3"}, clear=False):
                limits = get_trading_limits()
        assert limits == {"maxOpenOrdersTotal": 8, "maxOpenOrdersPerCoin": 2}

    def test_env_fallback_when_config_missing_fields(self):
        with patch(
            "app.services.config_loader.load_config",
            return_value={"trading_limits": {}},
        ):
            with patch.dict(
                os.environ,
                {"SYSTEM_CORE_MAX_OPEN_TRADES": "7", "SYSTEM_CORE_MAX_OPEN_PER_COIN": "3"},
                clear=False,
            ):
                limits = get_trading_limits()
        assert limits == {"maxOpenOrdersTotal": 7, "maxOpenOrdersPerCoin": 3}


class TestMaxOpenTradesFromConfig:
    def test_blocks_at_configured_total(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_resolve_max_open_trades", return_value=3):
                with patch.object(scg, "_resolve_max_open_per_coin", return_value=1):
                    with patch(
                        "app.services.order_position_service.count_open_positions_for_symbol",
                        return_value=0,
                    ):
                        with patch.object(
                            scg,
                            "count_distinct_symbols_with_open_positions",
                            return_value=3,
                        ):
                            allowed, reason = scg.check_system_core_buy_allowed(
                                mock_db,
                                "ETH_USDT",
                                100.0,
                                rsi=30.0,
                                ma200=None,
                                price=3000.0,
                            )
        assert allowed is False
        assert "system_core_max_open_trades" in reason
        assert "max=3" in reason

    def test_allows_below_configured_total(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_resolve_max_open_trades", return_value=5):
                with patch.object(scg, "_resolve_max_open_per_coin", return_value=1):
                    with patch(
                        "app.services.order_position_service.count_open_positions_for_symbol",
                        return_value=0,
                    ):
                        with patch.object(
                            scg,
                            "count_distinct_symbols_with_open_positions",
                            return_value=4,
                        ):
                            allowed, reason = scg.check_system_core_buy_allowed(
                                mock_db,
                                "ETH_USDT",
                                100.0,
                                rsi=30.0,
                                ma200=None,
                                price=3000.0,
                            )
        assert allowed is True
        assert reason == ""


class TestMaxOpenPerCoinFromConfig:
    def test_blocks_at_configured_per_coin_limit(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_resolve_max_open_per_coin", return_value=2):
                with patch(
                    "app.services.order_position_service.count_open_positions_for_symbol",
                    return_value=2,
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

    def test_allows_one_position_when_limit_is_two(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_resolve_max_open_per_coin", return_value=2):
                with patch.object(scg, "_resolve_max_open_trades", return_value=5):
                    with patch(
                        "app.services.order_position_service.count_open_positions_for_symbol",
                        return_value=1,
                    ):
                        with patch.object(
                            scg,
                            "count_distinct_symbols_with_open_positions",
                            return_value=0,
                        ):
                            allowed, reason = scg.check_system_core_buy_allowed(
                                mock_db,
                                "ETH_USDT",
                                100.0,
                                rsi=30.0,
                                ma200=None,
                                price=3000.0,
                            )
        assert allowed is True
        assert reason == ""

    def test_resolve_reads_from_config_loader(self):
        with patch(
            "app.services.config_loader.get_trading_limits",
            return_value={"maxOpenOrdersTotal": 9, "maxOpenOrdersPerCoin": 4},
        ):
            assert scg._resolve_max_open_trades() == 9
            assert scg._resolve_max_open_per_coin() == 4
