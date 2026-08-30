"""Lots pinned only for visibility must not inflate the aggregates.

The aligner deliberately keeps a direction-aligned naked lot visible so a real
fill whose SL/TP failed stays on screen (prod ETH_USDT 5755600492671134850).
Measured in production on 30-ago-2026, that visibility rule was also inflating
every quantity aggregate with inventory that cannot exist:

    ALGO_USD  wallet -1136.02  ->  aligner reported 2731.00  (+1595.02)
    APT_USD   wallet  -184.13  ->  aligner reported  218.54  (+34.41)
    HBAR_USD  wallet -1349.93  ->  aligner reported 1411.00  (+61.07)

The row stays. The arithmetic does not count it.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.expected_take_profit import (
    _align_open_lots_to_wallet,
    lot_exceeds_wallet,
    rebuild_open_lots,
    split_lots_by_wallet_capacity,
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


def _order(db, oid, *, side, qty, price, when, symbol="ALGO_USD", role=None, parent=None,
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


def _algo_shaped_books(db):
    """Reproduces the live ALGO_USD shape: one protected short filling the wallet
    plus three older naked shorts that the aligner pins one by one."""
    t = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)
    # protected short = the real position, exactly the wallet
    _order(db, "PROT", side=OrderSideEnum.SELL, qty="1136", price="0.20", when=t)
    _order(db, "PROT-TP", side=OrderSideEnum.BUY, qty="1136", price="0.18", when=t,
           role="TAKE_PROFIT", parent="PROT", status=OrderStatusEnum.ACTIVE,
           order_type="TAKE_PROFIT_LIMIT")
    # naked leftovers, direction-aligned, each individually <= |wallet|
    _order(db, "GHOST-A", side=OrderSideEnum.SELL, qty="718", price="0.22",
           when=t - timedelta(days=19))
    _order(db, "GHOST-B", side=OrderSideEnum.SELL, qty="805", price="0.23",
           when=t - timedelta(days=17))
    _order(db, "GHOST-C", side=OrderSideEnum.SELL, qty="72", price="0.21",
           when=t - timedelta(days=9))


def test_phantom_lots_stay_visible_but_are_tagged(db_session):
    _algo_shaped_books(db_session)
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    aligned, warning = _align_open_lots_to_wallet(db_session, lots, Decimal("-1136"))

    # visibility preserved: every pinned lot is still returned
    assert len(aligned) == 4
    assert warning == "lots_exceed_wallet"

    tagged = [l for l in aligned if lot_exceeds_wallet(l)]
    untagged = [l for l in aligned if not lot_exceeds_wallet(l)]

    # the protected lot alone fills the wallet, so all three naked ones are phantom
    assert {l.buy_order_id for l in untagged} == {"PROT"}
    assert {l.buy_order_id for l in tagged} == {"GHOST-A", "GHOST-B", "GHOST-C"}

    # and the countable quantity now equals wallet truth
    assert sum((l.lot_qty for l in untagged), Decimal("0")) == Decimal("1136")


def test_lots_within_wallet_are_never_tagged(db_session):
    """Control: when everything fits, nothing is tagged and nothing changes."""
    t = datetime(2026, 8, 29, tzinfo=timezone.utc)
    _order(db_session, "A", side=OrderSideEnum.SELL, qty="100", price="0.20", when=t)
    _order(db_session, "B", side=OrderSideEnum.SELL, qty="50", price="0.21", when=t)
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    aligned, warning = _align_open_lots_to_wallet(db_session, lots, Decimal("-150"))
    assert len(aligned) == 2
    assert warning is None
    assert not any(lot_exceeds_wallet(l) for l in aligned)


def test_protected_lots_are_never_tagged_as_phantom(db_session):
    """A protected lot is the live position: it is never classified as phantom,
    even when the protected sum alone exceeds the wallet."""
    t = datetime(2026, 8, 29, tzinfo=timezone.utc)
    for n, qty in (("P1", "800"), ("P2", "800")):
        _order(db_session, n, side=OrderSideEnum.SELL, qty=qty, price="0.20", when=t)
        _order(db_session, n + "-TP", side=OrderSideEnum.BUY, qty=qty, price="0.18", when=t,
               role="TAKE_PROFIT", parent=n, status=OrderStatusEnum.ACTIVE,
               order_type="TAKE_PROFIT_LIMIT")
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    within, exceeding = split_lots_by_wallet_capacity(db_session, lots, Decimal("1000"))
    assert exceeding == []
    assert len(within) == 2


def test_newest_naked_lot_survives_oldest_falls_out(db_session):
    """The ghost signature is age: with partial capacity, the newest naked fill
    is the one more likely to be real, so it is the one kept."""
    t = datetime(2026, 8, 29, tzinfo=timezone.utc)
    _order(db_session, "OLD", side=OrderSideEnum.SELL, qty="100", price="0.20",
           when=t - timedelta(days=90))
    _order(db_session, "NEW", side=OrderSideEnum.SELL, qty="100", price="0.20", when=t)
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    within, exceeding = split_lots_by_wallet_capacity(db_session, lots, Decimal("-100"))
    assert [l.buy_order_id for l in within] == ["NEW"]
    assert [l.buy_order_id for l in exceeding] == ["OLD"]


def test_zero_wallet_tags_nothing(db_session):
    """With no wallet there is no capacity question to answer; caller decides."""
    t = datetime(2026, 8, 29, tzinfo=timezone.utc)
    _order(db_session, "A", side=OrderSideEnum.SELL, qty="10", price="0.20", when=t)
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    within, exceeding = split_lots_by_wallet_capacity(db_session, lots, Decimal("0"))
    assert exceeding == []
    assert len(within) == 1


# --- Hallazgos de Cursor Bugbot sobre la primera version de este cambio ---


def _algo_shaped_with_protection(db):
    """ALGO shape but with the naked lots also carrying an ACTIVE TP, so they
    land in all_matched and reach the coverage arithmetic."""
    t = datetime(2026, 8, 29, 20, 0, tzinfo=timezone.utc)
    _order(db, "PROT", side=OrderSideEnum.SELL, qty="1136", price="0.20", when=t)
    _order(db, "PROT-TP", side=OrderSideEnum.BUY, qty="1136", price="0.18", when=t,
           role="TAKE_PROFIT", parent="PROT", status=OrderStatusEnum.ACTIVE,
           order_type="TAKE_PROFIT_LIMIT")
    # phantom with a TP that is not parent-linked -> matched by FIFO, still naked
    _order(db, "GHOST", side=OrderSideEnum.SELL, qty="800", price="0.22",
           when=t - timedelta(days=19))


def test_summary_coverage_excludes_phantom_lots(db_session):
    """Bugbot (medium): covered_qty counted phantom lots, so the summary could
    claim a fully covered wallet while the details path still reported
    uncovered size. Both sides of the ratio must ignore them."""
    from app.services.expected_take_profit import _compute_expected_tp_for_lots

    _algo_shaped_with_protection(db_session)
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    aligned, _ = _align_open_lots_to_wallet(db_session, lots, Decimal("-1136"))
    assert any(lot_exceeds_wallet(l) for l in aligned), "el fixture debe producir un fantasma"

    out = _compute_expected_tp_for_lots(
        db_session, "ALGO_USD", aligned, Decimal("-1136"), current_price=0.19
    )
    # coverage never counts inventory that cannot exist
    assert out["covered_qty"] + out["uncovered_qty"] <= out["net_qty"] + 1e-6
    assert out["entry_lot_count"] == 1
    assert out["lots_exceeding_wallet"] == 1


def test_entry_rows_carry_the_flag(db_session):
    """Bugbot (low): the details UI renders entry_orders, not matched_lots, so
    the flag has to reach those rows or the phantom is indistinguishable."""
    from app.services.expected_take_profit import build_entry_orders_details

    _algo_shaped_by_ghosts = _algo_shaped_with_protection(db_session)
    lots = rebuild_open_lots(db_session, "ALGO_USD")
    aligned, _ = _align_open_lots_to_wallet(db_session, lots, Decimal("-1136"))
    rows = build_entry_orders_details(db_session, aligned, current_price=0.19)

    assert rows, "deberia haber filas de entrada"
    assert all("exceeds_wallet" in r for r in rows), "toda fila lleva la marca"
    marked = [r for r in rows if r["exceeds_wallet"]]
    assert [r["order_id"] for r in marked] == ["GHOST"]
