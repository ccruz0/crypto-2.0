"""Tests for Expected TP orphaned-protection view (balance <= 0, active SL/TP)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    build_orphaned_protection_lots,
    get_expected_take_profit_details,
    get_expected_take_profit_summary,
)


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    for table in Base.metadata.tables.values():
        try:
            table.create(bind=engine, checkfirst=True)
        except OperationalError as exc:
            if "already exists" not in str(exc).lower():
                raise

    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _add_dot_scenario(db_session, *, include_sell: bool = True) -> None:
    """DOT-like: filled buy + sell closes FIFO position; TP/SL remain active."""
    t0 = datetime(2026, 7, 1, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 7, 2, 10, 0, 0, tzinfo=timezone.utc)

    parent_buy = ExchangeOrder(
        exchange_order_id="5755600491599560690",
        symbol="DOT_USD",
        side=OrderSideEnum.BUY,
        order_type="LIMIT",
        status=OrderStatusEnum.FILLED,
        price=Decimal("4.50"),
        quantity=Decimal("100"),
        cumulative_quantity=Decimal("100"),
        exchange_create_time=t0,
    )
    tp = ExchangeOrder(
        exchange_order_id="73817490101971168",
        symbol="DOT_USD",
        side=OrderSideEnum.SELL,
        order_type="TAKE_PROFIT_LIMIT",
        order_role="TAKE_PROFIT",
        status=OrderStatusEnum.ACTIVE,
        price=Decimal("5.00"),
        quantity=Decimal("100"),
        cumulative_quantity=Decimal("0"),
        parent_order_id="5755600491599560690",
        exchange_create_time=t1,
    )
    sl = ExchangeOrder(
        exchange_order_id="73817490101968821",
        symbol="DOT_USD",
        side=OrderSideEnum.SELL,
        order_type="STOP_LIMIT",
        order_role="STOP_LOSS",
        status=OrderStatusEnum.ACTIVE,
        price=Decimal("4.00"),
        quantity=Decimal("100"),
        cumulative_quantity=Decimal("0"),
        parent_order_id="5755600491599560690",
        exchange_create_time=t1,
    )
    db_session.add_all([parent_buy, tp, sl])

    if include_sell:
        sell = ExchangeOrder(
            exchange_order_id="5755600491600000001",
            symbol="DOT_USD",
            side=OrderSideEnum.SELL,
            order_type="LIMIT",
            status=OrderStatusEnum.FILLED,
            price=Decimal("4.60"),
            quantity=Decimal("100"),
            cumulative_quantity=Decimal("100"),
            exchange_create_time=t1,
        )
        db_session.add(sell)

    db_session.commit()


def test_build_orphaned_protection_lots_after_position_closed(db_session):
    _add_dot_scenario(db_session)

    lots = build_orphaned_protection_lots(db_session, "DOT_USD")

    assert len(lots) == 1
    assert lots[0].buy_order_id == "5755600491599560690"
    assert lots[0].lot_qty == Decimal("100")
    assert lots[0].buy_price == Decimal("4.50")
    assert getattr(lots[0], "orphaned_protection", False) is True


def test_details_surfaces_orphaned_protection_when_balance_zero(db_session):
    _add_dot_scenario(db_session)

    details = get_expected_take_profit_details(
        db_session,
        "DOT_USD",
        current_price=4.55,
        portfolio_balance=0.0,
    )

    assert details["orphaned_protection_only"] is True
    assert details["net_qty"] == 100.0
    assert details["covered_qty"] == 100.0
    assert details["total_expected_profit"] == pytest.approx(50.0)
    assert len(details["entry_orders"]) == 1
    assert details["entry_orders"][0]["order_id"] == "5755600491599560690"
    assert len(details["entry_orders"][0]["take_profits"]) == 1
    assert details["entry_orders"][0]["stop_loss"] is not None


def test_summary_includes_symbol_with_negative_balance_and_orphaned_protection(db_session):
    _add_dot_scenario(db_session)

    summary = get_expected_take_profit_summary(
        db_session,
        portfolio_assets=[
            {
                "coin": "DOT",
                "balance": -0.5,
                "value_usd": -2.25,
            }
        ],
        market_prices={"DOT": 4.50},
    )

    assert "DOT_USD" in summary
    row = summary["DOT_USD"]
    assert row["orphaned_protection_only"] is True
    assert row["covered_qty"] == 100.0
    assert row["total_expected_profit"] == pytest.approx(50.0)
