"""Tests for trading limits config resolution and guardrail wiring."""

import os
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.services import system_core_trade_guards as scg
from app.services.config_loader import get_trading_limits
from app.utils import trading_guardrails as tg


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


class TestGetTradingLimits:
    def test_defaults_when_config_empty(self):
        with patch("app.services.config_loader.load_config", return_value={}):
            with patch.dict(
                os.environ,
                {
                    "MAX_OPEN_ORDERS_TOTAL": "10",
                    "MAX_OPEN_ORDERS_PER_SYMBOL": "3",
                    "MAX_USD_PER_ORDER": "100",
                    "MIN_SECONDS_BETWEEN_ORDERS": "600",
                    "MAX_ORDERS_PER_SYMBOL_PER_DAY": "2",
                },
                clear=False,
            ):
                limits = get_trading_limits()
        assert limits == {
            "maxOpenOrdersTotal": 10,
            "maxOpenOrdersPerCoin": 3,
            "maxUsdPerOrder": 100.0,
            "minSecondsBetweenOrders": 600,
            "maxOrdersPerSymbolPerDay": 2,
        }

    def test_config_overrides_env_for_per_coin(self):
        with patch(
            "app.services.config_loader.load_config",
            return_value={
                "trading_limits": {
                    "maxOpenOrdersTotal": 8,
                    "maxOpenOrdersPerCoin": 2,
                    "maxUsdPerOrder": 250,
                    "minSecondsBetweenOrders": 120,
                    "maxOrdersPerSymbolPerDay": 5,
                }
            },
        ):
            with patch.dict(os.environ, {"MAX_OPEN_ORDERS_TOTAL": "10"}, clear=False):
                limits = get_trading_limits()
        assert limits["maxOpenOrdersTotal"] == 8
        assert limits["maxOpenOrdersPerCoin"] == 2
        assert limits["maxUsdPerOrder"] == 250.0
        assert limits["minSecondsBetweenOrders"] == 120
        assert limits["maxOrdersPerSymbolPerDay"] == 5

    def test_saved_max_open_orders_total_wins_over_env(self):
        """Global Settings save must not be silently capped by MAX_OPEN_ORDERS_TOTAL env."""
        with patch(
            "app.services.config_loader.load_config",
            return_value={"trading_limits": {"maxOpenOrdersTotal": 30}},
        ):
            with patch.dict(os.environ, {"MAX_OPEN_ORDERS_TOTAL": "10"}, clear=False):
                limits = get_trading_limits()
        assert limits["maxOpenOrdersTotal"] == 30

    def test_env_fallback_when_config_missing_fields(self):
        with patch(
            "app.services.config_loader.load_config",
            return_value={"trading_limits": {}},
        ):
            with patch.dict(
                os.environ,
                {
                    "MAX_OPEN_ORDERS_TOTAL": "7",
                    "MAX_OPEN_ORDERS_PER_SYMBOL": "4",
                },
                clear=False,
            ):
                limits = get_trading_limits()
        assert limits["maxOpenOrdersTotal"] == 7
        assert limits["maxOpenOrdersPerCoin"] == 4


class TestTradingGuardrailsReadConfig:
    def test_resolve_max_open_orders_total_from_config(self):
        with patch(
            "app.services.config_loader.get_trading_limits",
            return_value={"maxOpenOrdersTotal": 12, "maxOpenOrdersPerCoin": 3},
        ):
            assert tg.resolve_max_open_orders_total() == 12

    def test_blocks_at_configured_total(self, mock_db):
        with patch.object(tg, "resolve_max_open_orders_total", return_value=3):
            with patch(
                "app.utils.trading_guardrails.count_total_open_positions",
                return_value=3,
            ):
                allowed, reason = tg._check_risk_limits(
                    mock_db,
                    "ETH_USDT",
                    50.0,
                    "BUY",
                    ignore_daily_limit=True,
                    ignore_cooldown=True,
                )
        assert allowed is False
        assert "MAX_OPEN_ORDERS_TOTAL" in (reason or "")


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
