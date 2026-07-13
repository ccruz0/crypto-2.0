"""Tests for filled entry order detection (long BUY + short SELL entries)."""

from decimal import Decimal
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.utils.filled_entry_order import is_filled_entry_order, is_filled_entry_exchange_order


@pytest.mark.parametrize(
    "status,side,order_role,order_type,expected",
    [
        ("FILLED", "BUY", None, "LIMIT", True),
        ("FILLED", "SELL", None, "LIMIT", True),
        ("FILLED", "SELL", None, "MARKET", True),
        ("FILLED", "BUY", "STOP_LOSS", "STOP_LIMIT", False),
        ("FILLED", "SELL", "TAKE_PROFIT", "TAKE_PROFIT_LIMIT", False),
        ("FILLED", "BUY", None, "STOP_LOSS", False),
        ("FILLED", "SELL", None, "TAKE_PROFIT", False),
        ("ACTIVE", "BUY", None, "LIMIT", False),
        ("CANCELLED", "SELL", None, "LIMIT", False),
    ],
)
def test_is_filled_entry_order(status, side, order_role, order_type, expected):
    assert is_filled_entry_order(
        status=status,
        side=side,
        order_role=order_role,
        order_type=order_type,
    ) is expected


@pytest.fixture
def db_session():
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


def _make_order(db_session, **kwargs) -> ExchangeOrder:
    now = datetime.now(timezone.utc)
    order = ExchangeOrder(
        exchange_order_id=kwargs.get("exchange_order_id", "entry-1"),
        symbol=kwargs.get("symbol", "ETH_USDT"),
        side=kwargs.get("side", OrderSideEnum.SELL),
        order_type=kwargs.get("order_type", "LIMIT"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal("70000"),
        quantity=Decimal("0.01"),
        cumulative_quantity=Decimal("0.01"),
        cumulative_value=Decimal("700"),
        avg_price=Decimal("70000"),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_short_sell_entry_detected(db_session):
    order = _make_order(db_session, exchange_order_id="5755600491599559568")
    assert is_filled_entry_exchange_order(order) is True


def test_linked_protection_flags_for_short_entry(db_session):
    """Regression: SELL entry with TP/SL children should not be orphan."""
    from app.utils.filled_entry_order import PROTECTION_ROLES

    parent = _make_order(
        db_session,
        exchange_order_id="5755600491599559568",
        side=OrderSideEnum.SELL,
    )
    now = datetime.now(timezone.utc)
    tp = ExchangeOrder(
        exchange_order_id="tp-child",
        symbol="ETH_USD",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        status=OrderStatusEnum.ACTIVE,
        order_role="TAKE_PROFIT",
        parent_order_id=parent.exchange_order_id,
        price=Decimal("71351"),
        quantity=Decimal("0.0135"),
        cumulative_quantity=Decimal("0"),
        cumulative_value=Decimal("0"),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    sl = ExchangeOrder(
        exchange_order_id="sl-child",
        symbol="ETH_USD",
        side=OrderSideEnum.BUY,
        order_type="STOP_LIMIT",
        status=OrderStatusEnum.ACTIVE,
        order_role="STOP_LOSS",
        parent_order_id=parent.exchange_order_id,
        price=Decimal("68823"),
        quantity=Decimal("0.0135"),
        cumulative_quantity=Decimal("0"),
        cumulative_value=Decimal("0"),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add_all([tp, sl])
    db_session.commit()

    entry_ids = [
        o.exchange_order_id
        for o in db_session.query(ExchangeOrder).all()
        if is_filled_entry_exchange_order(o)
    ]
    assert parent.exchange_order_id in entry_ids

    from app.services.sl_tp_protection import ACTIVE_PROTECTION_STATUSES

    linked = db_session.query(ExchangeOrder).filter(
        ExchangeOrder.parent_order_id.in_(entry_ids),
        ExchangeOrder.order_role.in_(list(PROTECTION_ROLES)),
        ExchangeOrder.status.in_(ACTIVE_PROTECTION_STATUSES + [OrderStatusEnum.FILLED]),
    ).all()
    parents_with_tp = {
        p.parent_order_id for p in linked if p.order_role == "TAKE_PROFIT"
    }
    parents_with_sl = {
        p.parent_order_id for p in linked if p.order_role == "STOP_LOSS"
    }

    assert parent.exchange_order_id in parents_with_tp
    assert parent.exchange_order_id in parents_with_sl
    is_orphan = not (
        parent.exchange_order_id in parents_with_tp
        or parent.exchange_order_id in parents_with_sl
    )
    assert is_orphan is False
