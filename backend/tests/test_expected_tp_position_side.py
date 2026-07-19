"""Tests for Expected TP position side and entry-order side resolution."""

from decimal import Decimal
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    OpenLot,
    _compute_expected_tp_for_lots,
    build_entry_orders_details,
    resolve_position_side,
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
    now = datetime.now(timezone.utc)
    order = ExchangeOrder(
        exchange_order_id=kwargs["exchange_order_id"],
        symbol=kwargs.get("symbol", "ETH_USD"),
        side=kwargs.get("side", OrderSideEnum.BUY),
        order_type=kwargs.get("order_type", "LIMIT"),
        status=kwargs.get("status", OrderStatusEnum.FILLED),
        order_role=kwargs.get("order_role"),
        parent_order_id=kwargs.get("parent_order_id"),
        price=Decimal(str(kwargs.get("price", "70000"))),
        quantity=Decimal(str(kwargs.get("quantity", "0.0135"))),
        cumulative_quantity=Decimal(str(kwargs.get("cumulative_quantity", "0.0135"))),
        cumulative_value=Decimal("945"),
        avg_price=Decimal(str(kwargs.get("price", "70000"))),
        exchange_create_time=now,
        exchange_update_time=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(order)
    db_session.commit()
    return order


def test_resolve_position_side_long_from_buy_lots(db_session):
    buy = _add_order(db_session, exchange_order_id="buy-long", side=OrderSideEnum.BUY)
    lots = [
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("70000"),
            lot_qty=Decimal("0.0135"),
        )
    ]
    assert resolve_position_side(db_session, lots) == "LONG"


def test_resolve_position_side_short_from_sell_lots(db_session):
    sell = _add_order(
        db_session,
        exchange_order_id="sell-short",
        side=OrderSideEnum.SELL,
        symbol="ETH_USDT",
    )
    lots = [
        OpenLot(
            symbol="ETH_USDT",
            buy_order_id=sell.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("70000"),
            lot_qty=Decimal("0.05"),
        )
    ]
    assert resolve_position_side(db_session, lots) == "SHORT"


def test_resolve_position_side_mixed_when_long_and_short_lots(db_session):
    """Hedged / dual-direction open lots must not collapse to dominant SHORT/LONG."""
    buy = _add_order(
        db_session,
        exchange_order_id="buy-long-mixed",
        side=OrderSideEnum.BUY,
        symbol="ETH_USD",
        quantity="0.0788",
    )
    sell_a = _add_order(
        db_session,
        exchange_order_id="sell-short-a",
        side=OrderSideEnum.SELL,
        symbol="ETH_USD",
        quantity="0.0558",
    )
    sell_b = _add_order(
        db_session,
        exchange_order_id="sell-short-b",
        side=OrderSideEnum.SELL,
        symbol="ETH_USD",
        quantity="0.0532",
    )
    lots = [
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=sell_a.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("1790.66"),
            lot_qty=Decimal("0.0558"),
        ),
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("1740.5"),
            lot_qty=Decimal("0.0788"),
        ),
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=sell_b.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("1876.73"),
            lot_qty=Decimal("0.0532"),
        ),
    ]
    assert resolve_position_side(db_session, lots) == "MIXED"


def test_build_entry_orders_details_uses_actual_entry_side_and_symbol(db_session):
    buy = _add_order(
        db_session,
        exchange_order_id="5755600491599559568",
        side=OrderSideEnum.BUY,
        symbol="ETH_USD",
    )
    lots = [
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("70000"),
            lot_qty=Decimal("0.0135"),
        )
    ]
    entries = build_entry_orders_details(db_session, lots)
    assert len(entries) == 1
    assert entries[0]["side"] == "BUY"
    assert entries[0]["symbol"] == "ETH_USD"
    assert entries[0]["order_id"] == "5755600491599559568"
    assert entries[0]["entry_price"] == 70000.0


def test_compute_expected_tp_summary_includes_avg_entry_price(db_session):
    """Summary rows expose qty-weighted avg entry for the Expected TP table."""
    buy_a = _add_order(
        db_session,
        exchange_order_id="entry-a",
        side=OrderSideEnum.BUY,
        symbol="ETH_USD",
        price="100",
        quantity="2",
    )
    buy_b = _add_order(
        db_session,
        exchange_order_id="entry-b",
        side=OrderSideEnum.BUY,
        symbol="ETH_USD",
        price="200",
        quantity="1",
    )
    lots = [
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy_a.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("100"),
            lot_qty=Decimal("2"),
        ),
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy_b.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("200"),
            lot_qty=Decimal("1"),
        ),
    ]

    row = _compute_expected_tp_for_lots(
        db_session,
        "ETH_USD",
        lots,
        Decimal("3"),
        current_price=150.0,
    )

    assert row is not None
    # (100*2 + 200*1) / 3 = 133.333...
    assert row["avg_entry_price"] == pytest.approx(400 / 3)
    assert row["entry_lot_count"] == 2
    assert row["cost_basis_unknown"] is False


def test_compute_expected_tp_summary_avg_entry_null_when_cost_basis_unknown(db_session):
    buy = _add_order(
        db_session,
        exchange_order_id="entry-unknown",
        side=OrderSideEnum.BUY,
        symbol="ETH_USD",
        price="150",
    )
    lots = [
        OpenLot(
            symbol="ETH_USD",
            buy_order_id=buy.exchange_order_id,
            buy_time=datetime.now(timezone.utc),
            buy_price=Decimal("150"),
            lot_qty=Decimal("1"),
            cost_basis_unknown=True,
        )
    ]

    row = _compute_expected_tp_for_lots(
        db_session,
        "ETH_USD",
        lots,
        Decimal("1"),
        current_price=150.0,
    )

    assert row is not None
    assert row["avg_entry_price"] is None
    assert row["entry_lot_count"] == 1
    assert row["cost_basis_unknown"] is True
