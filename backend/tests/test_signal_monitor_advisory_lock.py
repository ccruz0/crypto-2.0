"""
Tests for signal monitor advisory lock lifecycle and successful-cycle health tracking.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, call, patch

import pytest
from sqlalchemy.orm import Session

from app.services.signal_monitor import (
    SIGNAL_MONITOR_LOCK_ID,
    SignalMonitorService,
)


@pytest.fixture
def monitor_service(tmp_path):
    svc = SignalMonitorService()
    svc.status_file_path = tmp_path / "signal_monitor_status.json"
    svc.last_successful_cycle_at = None
    svc.successful_cycle_count = 0
    svc.lock_acquisition_failures = 0
    svc.skipped_cycles = 0
    return svc


def _mock_db_session(dialect_name: str = "postgresql"):
    db = MagicMock(spec=Session)
    bind = MagicMock()
    bind.dialect.name = dialect_name
    db.get_bind.return_value = bind
    return db


def test_acquire_monitor_lock_success(monitor_service):
    db = _mock_db_session()
    db.execute.return_value.scalar.return_value = True

    assert monitor_service._acquire_monitor_lock(db) is True
    db.execute.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "pg_try_advisory_lock" in sql


def test_acquire_monitor_lock_failure(monitor_service):
    db = _mock_db_session()
    db.execute.return_value.scalar.return_value = False

    assert monitor_service._acquire_monitor_lock(db) is False


def test_release_monitor_lock_uses_unlock_all_on_postgresql(monitor_service):
    db = _mock_db_session("postgresql")

    monitor_service._release_monitor_lock(db, lock_acquired=True)

    db.execute.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "pg_advisory_unlock_all" in sql


def test_release_monitor_lock_skips_when_not_acquired_on_postgresql(monitor_service):
    """unlock_all still runs on pooled connections even when lock was not acquired."""
    db = _mock_db_session("postgresql")

    monitor_service._release_monitor_lock(db, lock_acquired=False)

    db.execute.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "pg_advisory_unlock_all" in sql


def test_release_monitor_lock_exception_path_still_attempts_unlock(monitor_service):
    db = _mock_db_session("postgresql")
    db.execute.side_effect = Exception("db error")

    monitor_service._release_monitor_lock(db, lock_acquired=True)
    db.execute.assert_called_once()


def _run_async(coro):
    return asyncio.run(coro)


def _run_one_cycle(monitor_service, db):
    async def _stop_after_sleep(_delay):
        monitor_service.is_running = False

    async def _run():
        with patch("app.services.signal_monitor.SessionLocal", return_value=db), patch(
            "app.services.system_alerts.evaluate_and_maybe_send_system_alert",
        ), patch("asyncio.sleep", side_effect=_stop_after_sleep):
            await monitor_service.start()

    _run_async(_run())


def test_monitor_cycle_releases_lock_on_success(monitor_service):
    db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, db)

    monitor_service._acquire_monitor_lock.assert_called_once()
    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service._release_monitor_lock.call_args[0][1] is True


def test_monitor_cycle_releases_lock_on_exception(monitor_service):
    db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock(side_effect=RuntimeError("monitor failed"))

    _run_one_cycle(monitor_service, db)

    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service._release_monitor_lock.call_args[0][1] is True
    assert monitor_service.successful_cycle_count == 0


def test_pool_reuse_unlock_all_called_before_close(monitor_service):
    db = _mock_db_session()
    lock_result = MagicMock()
    lock_result.scalar.return_value = True
    unlock_result = MagicMock()
    db.execute.side_effect = [lock_result, unlock_result]
    monitor_service.is_running = False
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, db)

    unlock_calls = [str(c[0][0]) for c in db.execute.call_args_list]
    assert any("pg_advisory_unlock_all" in sql for sql in unlock_calls)
    db.close.assert_called()


def test_run_locked_increments_skipped_and_does_not_update_success(monitor_service):
    db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=False)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, db)

    monitor_service.monitor_signals.assert_not_called()
    assert monitor_service.lock_acquisition_failures == 1
    assert monitor_service.skipped_cycles == 1
    assert monitor_service.last_successful_cycle_at is None
    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service._release_monitor_lock.call_args[0][1] is False


def test_successful_cycle_updates_last_successful_cycle_at(monitor_service):
    db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    before = datetime.now(timezone.utc)
    _run_one_cycle(monitor_service, db)

    assert monitor_service.last_successful_cycle_at is not None
    assert monitor_service.last_successful_cycle_at >= before
    assert monitor_service.successful_cycle_count == 1


def test_health_stale_when_no_successful_cycles():
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock_svc:
        mock_svc.is_running = True
        mock_svc.last_run_at = datetime.now(timezone.utc)
        mock_svc.last_successful_cycle_at = None
        mock_svc.successful_cycle_count = 0
        mock_svc.lock_acquisition_failures = 5
        mock_svc.skipped_cycles = 5

        result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["status"] == "WARN"
    assert result["last_successful_cycle_age_minutes"] is None
    assert result["last_cycle_age_minutes"] is not None
    assert result["lock_acquisition_failures"] == 5
    assert result["skipped_cycles"] == 5


def test_health_fail_when_successful_cycle_stale():
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock_svc:
        mock_svc.is_running = True
        mock_svc.last_run_at = datetime.now(timezone.utc)
        mock_svc.last_successful_cycle_at = datetime.now(timezone.utc) - timedelta(minutes=45)
        mock_svc.successful_cycle_count = 10
        mock_svc.lock_acquisition_failures = 0
        mock_svc.skipped_cycles = 0

        result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["status"] == "FAIL"
    assert result["last_successful_cycle_age_minutes"] > 30


def test_health_pass_after_successful_cycle():
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock_svc:
        mock_svc.is_running = True
        mock_svc.last_run_at = datetime.now(timezone.utc)
        mock_svc.last_successful_cycle_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        mock_svc.successful_cycle_count = 42
        mock_svc.lock_acquisition_failures = 0
        mock_svc.skipped_cycles = 0

        result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["status"] == "PASS"
    assert result["successful_cycle_count"] == 42
    assert result["last_successful_cycle_age_minutes"] < 30


def test_signal_monitor_lock_id_constant():
    assert SIGNAL_MONITOR_LOCK_ID == 123456
