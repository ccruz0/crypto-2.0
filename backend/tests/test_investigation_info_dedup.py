"""
Tests for investigation-complete Telegram message deduplication.

DB-backed dedup (TradingSettings) replaces volatile JSONL/memory. Ensures:
- First send allowed
- Second send within cooldown skipped
- Send after cooldown allowed
- Restart-safe (DB persists; in-memory cleared)
- Same task re-executed does not resend within cooldown
"""
import os
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.trading_settings import TradingSettings

# In-memory SQLite to avoid leftover DB files; only TradingSettings needed
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def setup_module(module):
    # Create only TradingSettings to avoid schema conflicts with full app models
    TradingSettings.__table__.create(engine, checkfirst=True)


def teardown_module(module):
    TradingSettings.__table__.drop(engine, checkfirst=True)


def _clear_dedup_keys(db_session):
    """Remove test dedup keys from TradingSettings."""
    prefix = "agent_info_dedup:investigation_complete:"
    rows = db_session.query(TradingSettings).filter(
        TradingSettings.setting_key.like(f"{prefix}%")
    ).all()
    for r in rows:
        db_session.delete(r)
    db_session.commit()


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _patch_session_local():
    """Patch SessionLocal to use test DB (agent_telegram_approval imports from app.database)."""
    with patch("app.database.SessionLocal", TestingSessionLocal):
        yield


@pytest.fixture
def clean_dedup(db_session):
    """Clear dedup state before test."""
    _clear_dedup_keys(db_session)
    yield
    _clear_dedup_keys(db_session)


def test_first_send_allowed(clean_dedup):
    """First send for a task should be allowed."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")

    with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
        mock_send.return_value = (True, 1001)

        from app.services.agent_telegram_approval import send_investigation_complete_info

        result = send_investigation_complete_info(
            task_id="test-task-001",
            title="Test Task",
            sections={"Root Cause": "Test", "Recommended Fix": "Fix it"},
        )

        assert result["sent"] is True
        assert result.get("skipped") is None
        mock_send.assert_called_once()


def test_second_send_within_cooldown_skipped(clean_dedup):
    """Second send for same task within cooldown should be skipped."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")

    with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
        mock_send.return_value = (True, 1001)

        from app.services.agent_telegram_approval import send_investigation_complete_info

        # First send
        r1 = send_investigation_complete_info(
            task_id="test-task-002",
            title="Test Task",
            sections={"Root Cause": "Test", "Recommended Fix": "Fix it"},
        )
        assert r1["sent"] is True

        # Second send immediately - should skip
        r2 = send_investigation_complete_info(
            task_id="test-task-002",
            title="Test Task",
            sections={"Root Cause": "Test", "Recommended Fix": "Fix it"},
        )
        assert r2["sent"] is False
        assert r2.get("skipped") == "dedup"
        assert mock_send.call_count == 1


def test_send_after_cooldown_allowed(clean_dedup):
    """Send after cooldown window should be allowed."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")

    task_id = "test-task-003"
    # Manually insert old timestamp (25h ago)
    db = TestingSessionLocal()
    try:
        from app.services.agent_telegram_approval import (
            _investigation_info_dedup_key,
            _INVESTIGATION_INFO_DEDUP_HOURS,
        )
        key = _investigation_info_dedup_key(task_id)
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=_INVESTIGATION_INFO_DEDUP_HOURS + 1))
        value = old_ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        db.add(TradingSettings(setting_key=key, setting_value=value))
        db.commit()
    finally:
        db.close()

    with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
        mock_send.return_value = (True, 1002)

        from app.services.agent_telegram_approval import send_investigation_complete_info

        result = send_investigation_complete_info(
            task_id=task_id,
            title="Test Task",
            sections={"Root Cause": "Test", "Recommended Fix": "Fix it"},
        )

        assert result["sent"] is True
        mock_send.assert_called_once()


def test_restart_safe_behavior(clean_dedup):
    """DB persists dedup state; second call (e.g. after restart) reads from DB and skips."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")

    with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
        mock_send.return_value = (True, 1001)

        from app.services.agent_telegram_approval import (
            send_investigation_complete_info,
            _investigation_info_dedup_key,
        )

        task_id = "test-task-004"
        # First send
        r1 = send_investigation_complete_info(
            task_id=task_id,
            title="Test Task",
            sections={"Root Cause": "Test", "Recommended Fix": "Fix it"},
        )
        assert r1["sent"] is True

    # Verify DB has the key (persistence)
    db = TestingSessionLocal()
    try:
        key = _investigation_info_dedup_key(task_id)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        assert row is not None
        assert row.setting_value  # ISO timestamp
    finally:
        db.close()

    # Second call (simulates different worker/restart - no in-memory state)
    with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
        from app.services.agent_telegram_approval import send_investigation_complete_info

        r2 = send_investigation_complete_info(
            task_id=task_id,
            title="Test Task",
            sections={"Root Cause": "Test", "Recommended Fix": "Fix it"},
        )
        assert r2["sent"] is False
        assert r2.get("skipped") == "dedup"
        mock_send.assert_not_called()


def test_same_task_reexecuted_no_resend_within_cooldown(clean_dedup):
    """Same task re-executed (e.g. scheduler retry) should not resend within cooldown."""
    os.environ.setdefault("TELEGRAM_BOT_TOKEN", "fake-token")
    os.environ.setdefault("TELEGRAM_CHAT_ID", "12345")

    with patch("app.services.agent_telegram_approval._send_telegram_message") as mock_send:
        mock_send.return_value = (True, 1001)

        from app.services.agent_telegram_approval import send_investigation_complete_info

        task_id = "31db1837-03fe-80d7-bf88-d802134064ad"
        sections = {"Root Cause": "Sync issue", "Recommended Fix": "Adjust logic"}

        # First execution
        r1 = send_investigation_complete_info(task_id=task_id, title="Fix sync", sections=sections)
        assert r1["sent"] is True

        # Simulate scheduler picking same task again (retry / re-execution)
        r2 = send_investigation_complete_info(task_id=task_id, title="Fix sync", sections=sections)
        assert r2["sent"] is False
        assert r2.get("skipped") == "dedup"

        # Third attempt
        r3 = send_investigation_complete_info(task_id=task_id, title="Fix sync", sections=sections)
        assert r3["sent"] is False

        assert mock_send.call_count == 1
