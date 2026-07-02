"""Guardrail position count: bot orders only, including short entries."""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.order_position_service import count_open_positions_for_symbol

BOT_SIGNAL_ID = 2001


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine, tables=[ExchangeOrder.__table__])
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine, tables=[ExchangeOrder.__table__])
        engine.dispose()


def _bot_order(**kwargs) -> ExchangeOrder:
    now = datetime.now(timezone.utc)
    return ExchangeOrder(
        exchange_order_id=kwargs.get("exchange_order_id", f"ord_{now.timestamp()}"),
        client_oid=None,
        symbol=kwargs.get("symbol", "ETH_USDT"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type="MARKET",
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        price=Decimal("3000"),
        quantity=kwargs.get("quantity", Decimal("1")),
        cumulative_quantity=kwargs.get("cumulative_quantity", kwargs.get("quantity", Decimal("1"))),
        cumulative_value=Decimal("3000"),
        avg_price=Decimal("3000"),
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


def test_manual_orders_excluded_from_count(db_session):
    """Exchange-synced orders without trade_signal_id must not affect guardrails."""
    manual = _bot_order(
        exchange_order_id="manual_buy",
        side=OrderSideEnum.BUY,
        trade_signal_id=None,
    )
    db_session.add(manual)
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 0


def test_bot_short_entry_counts_for_guardrail(db_session):
    """Filled bot SELL entry is one open short position for maxOpenOrdersPerCoin."""
    db_session.add(
        _bot_order(
            exchange_order_id="short_eth_1",
            side=OrderSideEnum.SELL,
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 1


def test_second_short_on_same_symbol_would_exceed_per_coin_cap(db_session):
    """Two filled short entries on one symbol => count 2 (guard max=1 would block)."""
    db_session.add_all(
        [
            _bot_order(
                exchange_order_id="short_eth_1",
                side=OrderSideEnum.SELL,
                trade_signal_id=BOT_SIGNAL_ID,
            ),
            _bot_order(
                exchange_order_id="short_eth_2",
                side=OrderSideEnum.SELL,
                trade_signal_id=BOT_SIGNAL_ID + 1,
            ),
        ]
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 2


def test_protection_sell_not_counted_as_short_position(db_session):
    db_session.add(
        _bot_order(
            exchange_order_id="tp_sell",
            side=OrderSideEnum.SELL,
            order_role="TAKE_PROFIT",
            trade_signal_id=None,
            parent_order_id="some_buy",
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 0


def test_bot_long_entry_unchanged(db_session):
    db_session.add(
        _bot_order(
            exchange_order_id="long_eth_1",
            side=OrderSideEnum.BUY,
        )
    )
    db_session.commit()

    assert count_open_positions_for_symbol(db_session, "ETH_USDT") == 1
