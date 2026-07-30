"""Tests for the watchdog Telegram button handling.

No network: the message-edit helper is stubbed out, so these exercise the
state machine only - which is the part that must not go wrong (an Ignore
that doesn't stick means the same alert every hour forever).

Destination: backend/tests/test_watchdog_inline.py
"""
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.watchdog import (
    WatchdogAnomaly,
    WatchdogFixRequest,
    ANOMALY_STATUS_ALERTED,
    ANOMALY_STATUS_IGNORED,
    ANOMALY_STATUS_FIX_REQUESTED,
    FIX_STATUS_PENDING,
)
from app.services import watchdog_inline as wi


@pytest.fixture()
def db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def no_telegram(monkeypatch):
    """Never touch the network; record the edits instead."""
    edits = []
    monkeypatch.setattr(wi, "_append_to_message", lambda *a, **k: edits.append(a))
    return edits


def _anomaly(db, **kw):
    defaults = dict(
        fingerprint="fp1",
        kind="MISSING_SL_TP",
        severity="high",
        symbol="SOL_USD",
        title="Entrada llenada SIN stop loss NI take profit",
        detail="detalle",
        evidence_json='{"entry_order_id": "E1"}',
        suspect_paths="app/services/exchange_sync.py",
        status=ANOMALY_STATUS_ALERTED,
        occurrences=1,
        telegram_message_id=555,
        telegram_chat_id="-100123",
    )
    defaults.update(kw)
    a = WatchdogAnomaly(**defaults)
    db.add(a)
    db.commit()
    db.refresh(a)
    return a


def test_markup_shape_and_callback_size():
    markup = wi.build_watchdog_inline_markup(1234)
    rows = markup["inline_keyboard"]
    payloads = [b["callback_data"] for row in rows for b in row]
    assert payloads == ["wd:i:1234", "wd:f:1234", "wd:d:1234"]
    # Telegram hard-limits callback_data to 64 bytes
    assert all(len(p.encode("utf-8")) <= 64 for p in payloads)


def test_ignore_marks_anomaly_ignored(db):
    a = _anomaly(db)
    reply = wi.handle_watchdog_callback(f"wd:i:{a.id}", "-100123", "42", db)
    db.refresh(a)
    assert a.status == ANOMALY_STATUS_IGNORED
    assert a.resolved_at is not None
    assert str(a.id) in reply


def test_fix_queues_a_request(db):
    a = _anomaly(db)
    reply = wi.handle_watchdog_callback(f"wd:f:{a.id}", "-100123", "42", db)
    db.refresh(a)
    assert a.status == ANOMALY_STATUS_FIX_REQUESTED
    fixes = db.query(WatchdogFixRequest).all()
    assert len(fixes) == 1
    assert fixes[0].anomaly_id == a.id
    assert fixes[0].status == FIX_STATUS_PENDING
    assert fixes[0].requested_by == "42"
    assert "encolado" in reply


def test_double_fix_press_does_not_queue_twice(db):
    a = _anomaly(db)
    wi.handle_watchdog_callback(f"wd:f:{a.id}", "-100123", "42", db)
    reply = wi.handle_watchdog_callback(f"wd:f:{a.id}", "-100123", "42", db)
    assert db.query(WatchdogFixRequest).count() == 1
    assert "ya hay un fix en curso" in reply.lower()


def test_detail_returns_evidence(db):
    a = _anomaly(db)
    reply = wi.handle_watchdog_callback(f"wd:d:{a.id}", "-100123", "42", db)
    assert "entry_order_id" in reply
    assert "E1" in reply
    # a detail view must not change state
    db.refresh(a)
    assert a.status == ANOMALY_STATUS_ALERTED


def test_unknown_anomaly_id_is_handled(db):
    reply = wi.handle_watchdog_callback("wd:i:99999", "-100123", "42", db)
    assert "no encontrada" in reply


def test_malformed_callback_is_handled(db):
    assert "no reconocido" in wi.handle_watchdog_callback("wd:i", "-100123", "42", db)
    assert "inválido" in wi.handle_watchdog_callback("wd:i:abc", "-100123", "42", db)
    assert "no reconocid" in wi.handle_watchdog_callback("wd:z:1", "-100123", "42", db)


def test_message_formatting_includes_key_fields(db):
    a = _anomaly(db, occurrences=3)
    body = wi.format_anomaly_message(a)
    assert "WATCHDOG" in body
    assert "MISSING_SL_TP" in body
    assert "SOL_USD" in body
    assert "HIGH" in body
    assert "Repeticiones: 3" in body
    assert "exchange_sync.py" in body
