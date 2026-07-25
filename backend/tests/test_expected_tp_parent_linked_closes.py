"""rebuild_open_lots must prefer OTOCO parent_order_id before FIFO.

Regression: BTC BUY 5755600489811716124 @ 60500 stayed uncovered/Missing SL/TP
after its linked TP 73817490102011214 FILLED, because pure FIFO consumed the
sell against older buys first.
"""

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import rebuild_open_lots


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
    qty = kwargs.get("quantity", "0.3")
    price = kwargs.get("price", "60000")
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "BTC_USD"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "MARKET"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal(str(price)),
        quantity=Decimal(str(qty)),
        cumulative_quantity=Decimal(str(kwargs.get("cumulative_quantity", qty))),
        cumulative_value=Decimal(str(kwargs.get("cumulative_value", Decimal(str(price)) * Decimal(str(qty))))),
        avg_price=Decimal(str(kwargs.get("avg_price", price))),
        exchange_create_time=now,
        exchange_update_time=kwargs.get("exchange_update_time", now),
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_filled_parent_linked_tp_closes_correct_buy_not_older_fifo(db_session):
    """Sold @60500 must leave inventory; older @71100 with active TP stays open."""
    t_old = datetime(2026, 6, 1, 15, 23, 44, tzinfo=timezone.utc)
    t_sold = datetime(2026, 6, 24, 15, 44, 30, tzinfo=timezone.utc)
    t_tp = datetime(2026, 7, 19, 10, 24, 53, tzinfo=timezone.utc)
    t_fill = datetime(2026, 7, 21, 7, 20, 13, tzinfo=timezone.utc)

    older = _add_order(
        db_session,
        exchange_order_id="5755600489289088548",
        price="71100",
        quantity="0.3",
        exchange_create_time=t_old,
    )
    sold = _add_order(
        db_session,
        exchange_order_id="5755600489811716124",
        price="60500",
        quantity="0.3",
        exchange_create_time=t_sold,
    )
    _add_order(
        db_session,
        exchange_order_id="73817490102011214",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        price="65945",
        avg_price="65960.21",
        quantity="0.3",
        parent_order_id=sold.exchange_order_id,
        exchange_create_time=t_tp,
        exchange_update_time=t_fill,
    )
    # Older lot still has active protection — must remain open.
    _add_order(
        db_session,
        exchange_order_id="73817490101936697",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="78000",
        quantity="0.3",
        cumulative_quantity="0",
        parent_order_id=older.exchange_order_id,
        exchange_create_time=t_old,
    )

    lots = rebuild_open_lots(db_session, "BTC_USD")
    lot_ids = {lot.buy_order_id for lot in lots}

    assert sold.exchange_order_id not in lot_ids
    assert older.exchange_order_id in lot_ids
    older_lot = next(lot for lot in lots if lot.buy_order_id == older.exchange_order_id)
    assert float(older_lot.lot_qty) == pytest.approx(0.3)


def test_extra_parent_linked_tps_do_not_fifo_onto_unrelated_buys(db_session):
    """Multiple FILLED TPs sharing one micro parent must not erode older lots."""
    t_old = datetime(2026, 6, 1, 15, 23, 44, tzinfo=timezone.utc)
    t_micro = datetime(2026, 7, 8, 12, 9, 24, tzinfo=timezone.utc)

    older = _add_order(
        db_session,
        exchange_order_id="5755600489289088548",
        price="71100",
        quantity="0.3",
        exchange_create_time=t_old,
    )
    micro = _add_order(
        db_session,
        exchange_order_id="5755600491541413116",
        price="62343.84",
        quantity="0.00016",
        exchange_create_time=t_micro,
    )
    for i, oid in enumerate(
        (
            "73817490101967200",
            "73817490101968336",
            "73817490102011217",
        )
    ):
        _add_order(
            db_session,
            exchange_order_id=oid,
            side=OrderSideEnum.SELL,
            order_type="TAKE_PROFIT_LIMIT",
            order_role="TAKE_PROFIT",
            price="65000",
            quantity="0.00016",
            parent_order_id=micro.exchange_order_id,
            exchange_create_time=datetime(2026, 7, 9 + i, 12, 0, 0, tzinfo=timezone.utc),
        )
    _add_order(
        db_session,
        exchange_order_id="73817490101936697",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price="78000",
        quantity="0.3",
        cumulative_quantity="0",
        parent_order_id=older.exchange_order_id,
        exchange_create_time=t_old,
    )

    lots = rebuild_open_lots(db_session, "BTC_USD")
    lot_ids = {lot.buy_order_id for lot in lots}

    assert micro.exchange_order_id not in lot_ids
    assert older.exchange_order_id in lot_ids
    older_lot = next(lot for lot in lots if lot.buy_order_id == older.exchange_order_id)
    assert float(older_lot.lot_qty) == pytest.approx(0.3)


def test_parent_linked_cover_buy_closes_short_entry(db_session):
    t_short = datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
    t_cover = datetime(2026, 7, 11, 12, 0, 0, tzinfo=timezone.utc)

    short = _add_order(
        db_session,
        exchange_order_id="sell-short-1",
        side=OrderSideEnum.SELL,
        price="1.0",
        quantity="100",
        symbol="DOGE_USD",
        exchange_create_time=t_short,
    )
    _add_order(
        db_session,
        exchange_order_id="cover-buy-1",
        side=OrderSideEnum.BUY,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        price="0.95",
        quantity="100",
        symbol="DOGE_USD",
        parent_order_id=short.exchange_order_id,
        exchange_create_time=t_cover,
    )

    lots = rebuild_open_lots(db_session, "DOGE_USD")
    assert lots == []
