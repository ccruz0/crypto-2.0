"""Tests for trading limits config resolution and guardrail wiring."""

import os
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services import system_core_trade_guards as scg
from app.services.config_loader import get_trading_limits
from app.utils import trading_guardrails as tg


@pytest.fixture
def mock_db():
    return MagicMock(spec=Session)


@pytest.fixture
def orders_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[ExchangeOrder.__table__])
    session = session_local()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=[ExchangeOrder.__table__])
        engine.dispose()


def _add_order(db, **kwargs) -> ExchangeOrder:
    now = datetime.now(timezone.utc)
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "ETH_USDT"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "MARKET"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal("1922.38"),
        quantity=Decimal("0.0052"),
        cumulative_quantity=Decimal("0.0052"),
        cumulative_value=Decimal("10"),
        avg_price=Decimal("1922.38"),
        exchange_create_time=kwargs.get("exchange_create_time", now),
        created_at=kwargs.get("created_at", now),
        updated_at=now,
    )
    db.add(order)
    db.commit()
    return order


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


class TestDailyLimitExcludesProtectiveOrders:
    """Regression: one entry + SL + TP must not exhaust MAX_ORDERS_PER_SYMBOL_PER_DAY=2."""

    def test_entry_plus_sl_tp_counts_as_one(self, orders_db):
        parent_id = "5755600492111379836"
        _add_order(orders_db, exchange_order_id=parent_id, order_role=None)
        _add_order(
            orders_db,
            exchange_order_id="sl-1",
            side=OrderSideEnum.SELL,
            order_type="STOP_LIMIT",
            status=OrderStatusEnum.ACTIVE,
            order_role="STOP_LOSS",
            parent_order_id=parent_id,
        )
        _add_order(
            orders_db,
            exchange_order_id="tp-1",
            side=OrderSideEnum.SELL,
            order_type="TAKE_PROFIT_LIMIT",
            status=OrderStatusEnum.ACTIVE,
            order_role="TAKE_PROFIT",
            parent_order_id=parent_id,
        )

        with patch.object(tg, "resolve_max_open_orders_total", return_value=10):
            with patch(
                "app.utils.trading_guardrails.count_total_open_positions",
                return_value=0,
            ):
                with patch.object(
                    tg, "_resolve_max_orders_per_symbol_per_day", return_value=2
                ):
                    allowed, reason = tg._check_risk_limits(
                        orders_db,
                        "ETH_USDT",
                        10.0,
                        "BUY",
                        ignore_usd_limit=True,
                        ignore_cooldown=True,
                    )

        assert allowed is True, reason
        assert reason is None

    def test_two_entries_still_block_at_limit_two(self, orders_db):
        _add_order(orders_db, exchange_order_id="entry-1", order_role=None)
        _add_order(orders_db, exchange_order_id="entry-2", order_role=None)

        with patch.object(tg, "resolve_max_open_orders_total", return_value=10):
            with patch(
                "app.utils.trading_guardrails.count_total_open_positions",
                return_value=0,
            ):
                with patch.object(
                    tg, "_resolve_max_orders_per_symbol_per_day", return_value=2
                ):
                    allowed, reason = tg._check_risk_limits(
                        orders_db,
                        "ETH_USDT",
                        10.0,
                        "BUY",
                        ignore_usd_limit=True,
                        ignore_cooldown=True,
                    )

        assert allowed is False
        assert "límite diario por símbolo" in (reason or "")
        assert "(2/2" in (reason or "")
