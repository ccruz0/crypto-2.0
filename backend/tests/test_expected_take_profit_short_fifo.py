"""FIFO matching must not pair SELL TPs with short (SELL entry) lots."""

from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    get_expected_take_profit_details,
    match_tp_orders_fifo,
)


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


def _add_order(db_session, **kwargs) -> ExchangeOrder:
    now = kwargs.get("exchange_create_time") or datetime.now(timezone.utc)
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "DOT_USD"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "LIMIT"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal(str(kwargs.get("price", "1"))),
        quantity=Decimal(str(kwargs.get("quantity", "10"))),
        cumulative_quantity=Decimal(
            str(
                kwargs.get(
                    "cumulative_quantity",
                    "0"
                    if kwargs.get("status") in (OrderStatusEnum.ACTIVE, OrderStatusEnum.NEW, OrderStatusEnum.PARTIALLY_FILLED)
                    else kwargs.get("quantity", "10"),
                )
            )
        ),
        cumulative_value=Decimal("100"),
        avg_price=Decimal(str(kwargs.get("price", "1"))),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_fifo_does_not_match_sell_tp_to_short_lot(db_session):
    """DOT-like case: orphan SELL TPs for closed longs must not cover short lots."""
    t_short = datetime(2026, 7, 4, 6, 54, 48, tzinfo=timezone.utc)
    t_long_tp = datetime(2026, 7, 7, 10, 0, 0, tzinfo=timezone.utc)

    short_sell = _add_order(
        db_session,
        exchange_order_id="5755600491330755974",
        side=OrderSideEnum.SELL,
        price="0.8742",
        quantity="9.28",
        exchange_create_time=t_short,
    )
    _add_order(
        db_session,
        exchange_order_id="5755600491468413585",
        side=OrderSideEnum.BUY,
        price="0.8577",
        quantity="11.65",
        exchange_create_time=datetime(2026, 7, 6, 8, 0, 0, tzinfo=timezone.utc),
    )
    wrong_tp = _add_order(
        db_session,
        exchange_order_id="73817490101971198",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.87",
        quantity="11.65",
        parent_order_id="5755600491468413585",
        exchange_create_time=t_long_tp,
    )

    from app.services.expected_take_profit import OpenLot

    short_lot = OpenLot(
        symbol="DOT_USD",
        buy_order_id=short_sell.exchange_order_id,
        buy_time=t_short,
        buy_price=Decimal("0.8742"),
        lot_qty=Decimal("9.28"),
    )

    result = match_tp_orders_fifo(db_session, [short_lot], [wrong_tp])

    assert result[0].matched_tp is None


def test_fifo_matches_buy_tp_to_short_lot(db_session):
    t_short = datetime(2026, 7, 6, 21, 13, 16, tzinfo=timezone.utc)
    t_tp = datetime(2026, 7, 6, 21, 13, 20, tzinfo=timezone.utc)

    short_sell = _add_order(
        db_session,
        exchange_order_id="5755600491455791519",
        side=OrderSideEnum.SELL,
        price="0.8996",
        quantity="11.09",
        exchange_create_time=t_short,
    )
    buy_tp = _add_order(
        db_session,
        exchange_order_id="73817490101971624",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.82",
        quantity="11.09",
        parent_order_id=None,
        exchange_create_time=t_tp,
    )

    from app.services.expected_take_profit import OpenLot

    short_lot = OpenLot(
        symbol="DOT_USD",
        buy_order_id=short_sell.exchange_order_id,
        buy_time=t_short,
        buy_price=Decimal("0.8996"),
        lot_qty=Decimal("11.09"),
    )

    result = match_tp_orders_fifo(db_session, [short_lot], [buy_tp])

    assert result[0].matched_tp is not None
    assert result[0].matched_tp.exchange_order_id == "73817490101971624"
    assert result[0].matched_tp.side == OrderSideEnum.BUY


def test_details_short_lot_unmatched_when_only_wrong_side_sell_tp(db_session):
    t_short = datetime(2026, 7, 4, 19, 3, 6, tzinfo=timezone.utc)

    _add_order(
        db_session,
        exchange_order_id="5755600491352963495",
        side=OrderSideEnum.SELL,
        price="0.8984",
        quantity="11.15",
        exchange_create_time=t_short,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490101971350",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="0.86",
        quantity="11.99",
        parent_order_id="5755600491541407094",
    )

    details = get_expected_take_profit_details(
        db_session,
        "DOT_USD",
        current_price=0.85,
        portfolio_balance=-11.15,
    )

    assert details["position_side"] == "SHORT"
    short_entry = details["entry_orders"][0]
    assert short_entry["side"] == "SELL"
    assert short_entry["take_profits"] == []
