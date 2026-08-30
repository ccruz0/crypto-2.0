"""Las firmas de verificacion del cierre de ghost lots no pueden dejar pasar
una posicion real, una operacion manual, ni tocar dos veces al mismo padre."""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.order_intent import OrderIntent
from scripts.close_ghost_lots_2026_08_30 import build_stubs, verify_target

NOW = datetime.now(timezone.utc)


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    sl = sessionmaker(bind=engine)
    Base.metadata.create_all(
        bind=engine, tables=[ExchangeOrder.__table__, OrderIntent.__table__]
    )
    s = sl()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _row(db, oid, *, side=OrderSideEnum.SELL, status=OrderStatusEnum.FILLED,
         role=None, otype="MARKET", parent=None, days_ago=30.0, qty=17.65,
         price=0.61, signal_id=99, created_days_ago=None):
    ts = NOW - timedelta(days=days_ago)
    created = NOW - timedelta(days=created_days_ago if created_days_ago is not None else days_ago)
    o = ExchangeOrder(exchange_order_id=oid, symbol="APT_USD", side=side,
                      order_type=otype, status=status, price=price, avg_price=price,
                      quantity=qty, cumulative_quantity=qty, order_role=role,
                      parent_order_id=parent, exchange_create_time=ts,
                      exchange_update_time=ts, created_at=created,
                      trade_signal_id=signal_id)
    db.add(o); db.commit()
    return o


def _ghost(db, oid, **kw):
    """Entrada corta del bot con ambas protecciones en estado terminal."""
    e = _row(db, oid, **kw)
    _row(db, f"{oid}-sl", side=OrderSideEnum.BUY, status=OrderStatusEnum.CANCELLED,
         role="STOP_LOSS", otype="STOP_LIMIT", parent=oid,
         days_ago=kw.get("days_ago", 30) - 1)
    _row(db, f"{oid}-tp", side=OrderSideEnum.BUY, status=OrderStatusEnum.REJECTED,
         role="TAKE_PROFIT", otype="TAKE_PROFIT_LIMIT", parent=oid,
         days_ago=kw.get("days_ago", 30) - 1)
    return e


def test_bot_ghost_is_accepted(db):
    _ghost(db, "ghost-1", days_ago=28)
    e, reason = verify_target(db, "ghost-1")
    assert reason is None
    stubs = build_stubs(e)
    assert len(stubs) == 2
    assert all(s.side == OrderSideEnum.BUY for s in stubs)
    assert all(str(s.parent_order_id) == "ghost-1" for s in stubs)
    assert all(float(s.avg_price) == 0.61 for s in stubs)


def test_manual_import_is_rejected(db):
    """El caso BTC del 5-ene importado en junio: sin signal ni intent."""
    _ghost(db, "manual-1", days_ago=200, signal_id=None)
    e, reason = verify_target(db, "manual-1")
    assert reason is not None and "no es entrada del bot" in reason


def test_age_uses_trade_time_not_import_time(db):
    """Una operacion RECIENTE importada hace meses no puede colarse por created_at."""
    _ghost(db, "recent-import", days_ago=2, created_days_ago=200)
    e, reason = verify_target(db, "recent-import")
    assert reason is not None and "reciente" in reason


def test_filled_child_blocks(db):
    _row(db, "real-1", days_ago=30)
    _row(db, "close-1", side=OrderSideEnum.BUY, role="STOP_LOSS",
         otype="STOP_LIMIT", parent="real-1", days_ago=29)
    e, reason = verify_target(db, "real-1")
    assert reason is not None and "FILLED" in reason


def test_active_child_blocks(db):
    _row(db, "live-1", days_ago=20)
    _row(db, "sl-live", side=OrderSideEnum.BUY, status=OrderStatusEnum.ACTIVE,
         role="STOP_LOSS", otype="STOP_LIMIT", parent="live-1", days_ago=20)
    e, reason = verify_target(db, "live-1")
    assert reason is not None and "no terminal" in reason


def test_childless_entry_is_flagged_not_closed(db):
    """Sin intento de proteccion: se revisa a mano, no se cierra a ciegas."""
    _row(db, "naked-1", days_ago=40)
    e, reason = verify_target(db, "naked-1")
    assert reason is not None and "sin hijos" in reason


def test_existing_stub_blocks_double_insert(db):
    _ghost(db, "ghost-2", days_ago=28)
    _row(db, "STUB-CLOSED-STOP_LOSS-ghost-2", side=OrderSideEnum.BUY,
         role="STOP_LOSS", otype="STOP_LIMIT", parent="ghost-2", days_ago=1)
    e, reason = verify_target(db, "ghost-2")
    assert reason is not None and "stub" in reason


def test_buy_entry_blocks(db):
    _ghost(db, "long-1", side=OrderSideEnum.BUY, days_ago=30)
    e, reason = verify_target(db, "long-1")
    assert reason is not None and "cortos" in reason


def test_intent_without_signal_id_still_counts_as_bot(db):
    """Origen de bot = signal_id O intent. Uno de los dos basta."""
    _ghost(db, "intent-only", days_ago=30, signal_id=None)
    db.add(OrderIntent(order_id="intent-only", symbol="APT_USD", side="SELL",
                       status="ORDER_PLACED", idempotency_key="k-intent-only"))
    db.commit()
    e, reason = verify_target(db, "intent-only")
    assert reason is None
