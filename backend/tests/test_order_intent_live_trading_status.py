"""Regression: BLOCKED_LIVE_TRADING must fit order_intents.status VARCHAR(20)."""
import os
import tempfile
import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.order_intent import OrderIntent, OrderIntentStatusEnum
from app.services.signal_order_orchestrator import create_order_intent


def _dedupe_table_indexes(table) -> None:
    seen = set()
    duplicates = []
    for idx in list(table.indexes):
        if idx.name in seen:
            duplicates.append(idx)
        else:
            seen.add(idx.name)
    for idx in duplicates:
        table.indexes.remove(idx)


@pytest.fixture()
def db_session():
    db_path = os.path.join(tempfile.gettempdir(), f"test_order_intent_{uuid.uuid4().hex}.db")
    engine = create_engine(
        f"sqlite:///{db_path}",
        connect_args={"check_same_thread": False},
    )
    _dedupe_table_indexes(OrderIntent.__table__)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        for suffix in ("", "-wal", "-shm"):
            try:
                os.remove(f"{db_path}{suffix}")
            except OSError:
                pass


def test_blocked_live_trading_status_length():
    status = OrderIntentStatusEnum.BLOCKED_LIVE_TRADING.value
    assert len(status) <= 20
    assert status == "BLOCKED_LIVE_TRADING"


def test_blocked_live_trading_intent_persists_when_live_off(db_session, monkeypatch):
    monkeypatch.setattr(
        "app.services.signal_order_orchestrator.get_live_trading_status",
        lambda _db: False,
    )

    order_intent, status = create_order_intent(
        db=db_session,
        signal_id=4242,
        symbol="DOT_USD",
        side="BUY",
        message_content="BUY SIGNAL DOT_USD 0.8292 test",
    )

    assert status == OrderIntentStatusEnum.BLOCKED_LIVE_TRADING.value
    assert order_intent is not None
    assert order_intent.status == OrderIntentStatusEnum.BLOCKED_LIVE_TRADING.value
    assert order_intent.error_message == "LIVE_TRADING is disabled"

    stored = db_session.query(OrderIntent).filter(OrderIntent.signal_id == 4242).one()
    assert stored.status == OrderIntentStatusEnum.BLOCKED_LIVE_TRADING.value
