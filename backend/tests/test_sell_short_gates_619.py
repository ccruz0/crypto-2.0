"""Issue #619: SELL/short entry gates mirror BUY (inverse RSI/MA200) + one short per symbol."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.portfolio import PortfolioBalance
from app.services import system_core_trade_guards as scg
from app.services.order_position_service import (
    count_open_short_positions_for_symbol,
    wallet_has_material_short,
)

BOT_SIGNAL_ID = 619001


@pytest.fixture
def mock_db():
    return MagicMock()


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(
        bind=engine,
        tables=[ExchangeOrder.__table__, PortfolioBalance.__table__],
    )
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(
            bind=engine,
            tables=[ExchangeOrder.__table__, PortfolioBalance.__table__],
        )
        engine.dispose()


def _bot_order(**kwargs) -> ExchangeOrder:
    now = datetime.now(timezone.utc)
    return ExchangeOrder(
        exchange_order_id=kwargs.get("exchange_order_id", f"ord_{now.timestamp()}"),
        client_oid=None,
        symbol=kwargs.get("symbol", "APT_USD"),
        side=kwargs.get("side", OrderSideEnum.SELL),
        order_type="MARKET",
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        price=Decimal("4.5"),
        quantity=kwargs.get("quantity", Decimal("10")),
        cumulative_quantity=kwargs.get("cumulative_quantity", kwargs.get("quantity", Decimal("10"))),
        cumulative_value=Decimal("45"),
        avg_price=Decimal("4.5"),
        trigger_condition=None,
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
        imported_at=None,
        trade_signal_id=kwargs.get("trade_signal_id", BOT_SIGNAL_ID),
        parent_order_id=kwargs.get("parent_order_id", None),
        oco_group_id=None,
        order_role=kwargs.get("order_role", None),
    )


class TestRsiInverseGate:
    def test_blocks_rsi_at_inverse_threshold_default(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                with patch.object(scg, "_SHORT_REGIME_ON", False):
                    with patch.object(scg, "_RSI_BUY_MAX", 40.0):
                        allowed, reason = scg.check_system_core_short_entry_allowed(
                            mock_db, "APT_USD", 100.0, price=4.5, rsi=60.0
                        )
        assert allowed is False
        assert "system_core_short_rsi" in reason
        assert "need_gt_60" in reason

    def test_allows_rsi_above_inverse_threshold(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                with patch.object(scg, "_SHORT_REGIME_ON", False):
                    with patch.object(scg, "_RSI_BUY_MAX", 40.0):
                        with patch(
                            "app.services.order_position_service.count_open_short_positions_for_symbol",
                            return_value=0,
                        ):
                            with patch(
                                "app.services.order_position_service.wallet_has_material_short",
                                return_value=False,
                            ):
                                with patch.object(
                                    scg, "count_distinct_symbols_with_open_positions", return_value=0
                                ):
                                    allowed, reason = scg.check_system_core_short_entry_allowed(
                                        mock_db, "APT_USD", 100.0, price=4.5, rsi=61.0
                                    )
        assert allowed is True
        assert reason == ""

    def test_allows_missing_rsi(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                with patch.object(scg, "_SHORT_REGIME_ON", False):
                    with patch(
                        "app.services.order_position_service.count_open_short_positions_for_symbol",
                        return_value=0,
                    ):
                        with patch(
                            "app.services.order_position_service.wallet_has_material_short",
                            return_value=False,
                        ):
                            with patch.object(
                                scg, "count_distinct_symbols_with_open_positions", return_value=0
                            ):
                                allowed, reason = scg.check_system_core_short_entry_allowed(
                                    mock_db, "APT_USD", 100.0, price=4.5, rsi=None
                                )
        assert allowed is True
        assert reason == ""

    def test_inverse_tracks_rsi_buy_max_env(self, mock_db):
        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                with patch.object(scg, "_SHORT_REGIME_ON", False):
                    with patch.object(scg, "_RSI_BUY_MAX", 50.0):
                        allowed, reason = scg.check_system_core_short_entry_allowed(
                            mock_db, "APT_USD", 100.0, price=4.5, rsi=50.0
                        )
        assert allowed is False
        assert "need_gt_50" in reason


class TestOneOpenShortPerSymbol:
    def test_blocks_second_bot_short_on_same_symbol(self, db_session):
        db_session.add(
            _bot_order(
                exchange_order_id="bonk_short_1",
                symbol="BONK_USD",
                side=OrderSideEnum.SELL,
                quantity=Decimal("100000"),
                cumulative_quantity=Decimal("100000"),
                price=Decimal("0.0001"),
                avg_price=Decimal("0.0001"),
            )
        )
        db_session.commit()

        assert count_open_short_positions_for_symbol(db_session, "BONK", last_price=0.0001) == 1

        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_SHORT_REGIME_ON", False):
                with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                    with patch.object(scg, "_resolve_max_open_per_coin", return_value=1):
                        with patch.object(scg, "_daily_drawdown_violation", return_value=(False, "")):
                            with patch.object(scg, "count_distinct_symbols_with_open_positions", return_value=1):
                                allowed, reason = scg.check_system_core_short_entry_allowed(
                                    db_session,
                                    "BONK_USD",
                                    100.0,
                                    price=0.0001,
                                    rsi=72.0,
                                )
        assert allowed is False
        assert reason == "system_core_one_open_short_per_symbol"

    def test_allows_first_short_when_only_long_exists(self, db_session):
        db_session.add(
            _bot_order(
                exchange_order_id="eth_long_1",
                symbol="ETH_USD",
                side=OrderSideEnum.BUY,
            )
        )
        db_session.commit()

        assert count_open_short_positions_for_symbol(db_session, "ETH") == 0

        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_SHORT_REGIME_ON", False):
                with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                    with patch.object(scg, "_daily_drawdown_violation", return_value=(False, "")):
                        with patch.object(scg, "count_distinct_symbols_with_open_positions", return_value=1):
                            allowed, reason = scg.check_system_core_short_entry_allowed(
                                db_session,
                                "ETH_USD",
                                100.0,
                                price=3000.0,
                                rsi=72.0,
                            )
        assert allowed is True
        assert reason == ""

    def test_blocks_when_wallet_has_material_short(self, db_session):
        db_session.add(
            PortfolioBalance(currency="BONK", balance=Decimal("-1000000"), usd_value=-50.0)
        )
        db_session.commit()

        assert wallet_has_material_short(db_session, "BONK_USD", last_price=0.00005) is True

        with patch.object(scg, "_GUARDS_ON", True):
            with patch.object(scg, "_SHORT_REGIME_ON", False):
                with patch.object(scg, "_LONG_BTC_REGIME_ON", False):
                    with patch.object(scg, "_daily_drawdown_violation", return_value=(False, "")):
                        with patch.object(scg, "count_distinct_symbols_with_open_positions", return_value=0):
                            allowed, reason = scg.check_system_core_short_entry_allowed(
                                db_session,
                                "BONK_USD",
                                100.0,
                                price=0.00005,
                                rsi=72.0,
                            )
        assert allowed is False
        assert reason == "system_core_one_open_short_per_symbol"
