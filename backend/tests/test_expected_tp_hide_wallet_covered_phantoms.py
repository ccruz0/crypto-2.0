"""Gated display filter for exceeds_wallet FIFO ghosts when wallet-sum covers (#617)."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    _align_open_lots_to_wallet,
    get_expected_take_profit_details,
    lot_exceeds_wallet,
    rebuild_open_lots,
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


def _order(db, oid, *, side, qty, price, when, symbol="BTC_USD", role=None, parent=None,
           status=OrderStatusEnum.FILLED, order_type="LIMIT"):
    o = ExchangeOrder(
        exchange_order_id=oid,
        symbol=symbol,
        side=side,
        order_type=order_type,
        status=status,
        order_role=role,
        parent_order_id=parent,
        price=Decimal(str(price)),
        quantity=Decimal(str(qty)),
        cumulative_quantity=Decimal(str(qty)) if status == OrderStatusEnum.FILLED else Decimal("0"),
        cumulative_value=Decimal("0"),
        avg_price=Decimal(str(price)),
        exchange_create_time=when,
        exchange_update_time=when,
        created_at=when,
        updated_at=when,
    )
    db.add(o)
    db.commit()
    return o


def _btc_short_with_fifo_ghosts(db):
    """Protected live short + older naked SELL FIFO ghosts (ALGO/BTC shape)."""
    t_old = datetime(2025, 11, 15, tzinfo=timezone.utc)
    t_live = datetime(2026, 8, 29, tzinfo=timezone.utc)

    for i, (oid, px, qty) in enumerate(
        (
            ("ghost-short-1", "75000", "0.0008"),
            ("ghost-short-2", "82000", "0.0007"),
            ("ghost-short-3", "95000", "0.0006"),
        ),
        start=1,
    ):
        _order(
            db,
            oid,
            side=OrderSideEnum.SELL,
            qty=qty,
            price=px,
            when=t_old + timedelta(days=i * 30),
        )

    live = _order(
        db,
        "live-short",
        side=OrderSideEnum.SELL,
        qty="0.0013",
        price="79000",
        when=t_live,
    )
    _order(
        db,
        "live-tp",
        side=OrderSideEnum.BUY,
        qty="0.0013",
        price="77000",
        when=t_live,
        role="TAKE_PROFIT",
        parent=live.exchange_order_id,
        status=OrderStatusEnum.ACTIVE,
        order_type="TAKE_PROFIT_LIMIT",
    )
    _order(
        db,
        "live-sl",
        side=OrderSideEnum.BUY,
        qty="0.0013",
        price="75000",
        when=t_live,
        role="STOP_LOSS",
        parent=live.exchange_order_id,
        status=OrderStatusEnum.ACTIVE,
        order_type="STOP_LIMIT",
    )


def test_phantom_ghosts_tagged_on_short_wallet(db_session):
    _btc_short_with_fifo_ghosts(db_session)
    lots = rebuild_open_lots(db_session, "BTC_USD")
    aligned, warning = _align_open_lots_to_wallet(db_session, lots, Decimal("-0.0013"))
    phantoms = [lot for lot in aligned if lot_exceeds_wallet(lot)]
    real = [lot for lot in aligned if not lot_exceeds_wallet(lot)]
    assert real, "protected short must remain visible"
    assert phantoms, "older naked shorts must be tagged exceeds_wallet on short wallet"
    assert warning == "lots_exceed_wallet"


def test_flag_off_keeps_phantom_rows_in_details(db_session, monkeypatch):
    monkeypatch.delenv("EXPECTED_TP_HIDE_WALLET_COVERED_PHANTOMS", raising=False)
    _btc_short_with_fifo_ghosts(db_session)
    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=79000.0,
        portfolio_balance=-0.0013,
    )
    assert details.get("wallet_covered_phantoms_hidden", 0) == 0
    assert details.get("hide_wallet_covered_phantoms_enabled") is False
    assert any(row.get("exceeds_wallet") for row in details["entry_orders"])


def test_flag_on_hides_phantom_rows_when_wallet_sum_covers(db_session, monkeypatch):
    monkeypatch.setenv("EXPECTED_TP_HIDE_WALLET_COVERED_PHANTOMS", "true")
    _btc_short_with_fifo_ghosts(db_session)
    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=79000.0,
        portfolio_balance=-0.0013,
    )
    assert details.get("hide_wallet_covered_phantoms_enabled") is True
    assert details.get("wallet_covered_phantoms_hidden", 0) > 0
    assert not any(row.get("exceeds_wallet") for row in details["entry_orders"])
    assert details["entry_orders"]
    assert details["entry_orders"][0]["order_id"] == "live-short"


def test_flag_on_without_sl_tp_coverage_does_not_hide(db_session, monkeypatch):
    monkeypatch.setenv("EXPECTED_TP_HIDE_WALLET_COVERED_PHANTOMS", "true")
    t = datetime(2026, 8, 29, tzinfo=timezone.utc)
    _order(db_session, "naked-short", side=OrderSideEnum.SELL, qty="0.0013", price="79000", when=t)
    _order(db_session, "ghost-short", side=OrderSideEnum.SELL, qty="0.0005", price="75000",
           when=t - timedelta(days=60))
    details = get_expected_take_profit_details(
        db_session,
        "BTC_USD",
        current_price=79000.0,
        portfolio_balance=-0.0013,
    )
    assert details.get("wallet_covered_phantoms_hidden", 0) == 0
    assert details.get("hide_wallet_covered_phantoms_enabled") is False
