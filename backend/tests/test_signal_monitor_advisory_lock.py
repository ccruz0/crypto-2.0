"""
Tests for signal monitor advisory lock lifecycle, timeout, overlap skip, and health tracking.
"""
import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, Mock, patch

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
    svc.timeout_count = 0
    svc.overlap_skip_count = 0
    svc.last_timeout_at = None
    svc.monitor_cycle_timeout = 120.0
    svc._cycle_active = False
    return svc


def _mock_db_session(dialect_name: str = "postgresql"):
    db = MagicMock(spec=Session)
    bind = MagicMock()
    bind.dialect.name = dialect_name
    db.get_bind.return_value = bind
    return db


def test_acquire_monitor_lock_success_rolls_back_transaction(monitor_service):
    """A/B: dedicated lock session acquires lock and rolls back implicit transaction."""
    db = _mock_db_session()
    db.execute.return_value.scalar.return_value = True

    assert monitor_service._acquire_monitor_lock(db) is True
    db.execute.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "pg_try_advisory_lock" in sql
    db.rollback.assert_called_once()


def test_acquire_monitor_lock_failure_does_not_rollback(monitor_service):
    db = _mock_db_session()
    db.execute.return_value.scalar.return_value = False

    assert monitor_service._acquire_monitor_lock(db) is False
    db.rollback.assert_not_called()


def test_release_monitor_lock_uses_unlock_all_on_postgresql(monitor_service):
    db = _mock_db_session("postgresql")

    monitor_service._release_monitor_lock(db, lock_acquired=True, cycle_id="test-cycle")

    db.execute.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "pg_advisory_unlock_all" in sql
    db.rollback.assert_called_once()
    db.close.assert_called_once()


def test_release_monitor_lock_skips_when_not_acquired_on_postgresql(monitor_service):
    db = _mock_db_session("postgresql")

    monitor_service._release_monitor_lock(db, lock_acquired=False, cycle_id="test-cycle")

    db.execute.assert_called_once()
    sql = str(db.execute.call_args[0][0])
    assert "pg_advisory_unlock_all" in sql
    db.close.assert_called_once()


def test_release_monitor_lock_exception_path_still_closes(monitor_service):
    db = _mock_db_session("postgresql")
    db.execute.side_effect = Exception("db error")

    monitor_service._release_monitor_lock(db, lock_acquired=True, cycle_id="test-cycle")

    db.execute.assert_called_once()
    db.close.assert_called_once()


def _run_async(coro):
    return asyncio.run(coro)


def _run_one_cycle(monitor_service, lock_db, work_db=None):
    work_db = work_db or _mock_db_session()

    async def _stop_after_sleep(_delay):
        monitor_service.is_running = False

    session_calls = iter([lock_db, work_db])

    async def _run():
        with patch("app.services.signal_monitor.SessionLocal", side_effect=lambda: next(session_calls)), patch(
            "app.services.system_alerts.evaluate_and_maybe_send_system_alert",
        ), patch("asyncio.sleep", side_effect=_stop_after_sleep):
            await monitor_service.start()

    _run_async(_run())


def test_monitor_cycle_releases_lock_on_success(monitor_service):
    lock_db = _mock_db_session()
    work_db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, lock_db, work_db)

    monitor_service._acquire_monitor_lock.assert_called_once_with(lock_db)
    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service._release_monitor_lock.call_args[0][1] is True
    monitor_service.monitor_signals.assert_called_once_with(work_db)


def test_monitor_signals_uses_different_session_from_lock_connection(monitor_service):
    lock_db = _mock_db_session()
    work_db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, lock_db, work_db)

    lock_arg = monitor_service._acquire_monitor_lock.call_args[0][0]
    work_arg = monitor_service.monitor_signals.call_args[0][0]
    assert lock_arg is lock_db
    assert work_arg is work_db
    assert lock_arg is not work_arg


def test_monitor_cycle_releases_lock_on_exception(monitor_service):
    lock_db = _mock_db_session()
    work_db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock(side_effect=RuntimeError("monitor failed"))

    _run_one_cycle(monitor_service, lock_db, work_db)

    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service._release_monitor_lock.call_args[0][1] is True
    assert monitor_service.successful_cycle_count == 0


def test_timeout_path_releases_advisory_lock(monitor_service):
    lock_db = _mock_db_session()
    work_db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()

    async def _slow_monitor(_db):
        await asyncio.Event().wait()

    monitor_service.monitor_signals = _slow_monitor

    with patch("app.services.signal_monitor._monitor_cycle_timeout_seconds", return_value=0.01):
        _run_one_cycle(monitor_service, lock_db, work_db)

    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service.timeout_count == 1
    assert monitor_service.last_timeout_at is not None


def test_pool_reuse_unlock_all_called_before_close(monitor_service):
    lock_db = _mock_db_session()
    work_db = _mock_db_session()
    lock_result = MagicMock()
    lock_result.scalar.return_value = True
    unlock_result = MagicMock()
    lock_db.execute.side_effect = [lock_result, unlock_result]
    monitor_service.is_running = False
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, lock_db, work_db)

    unlock_calls = [str(c[0][0]) for c in lock_db.execute.call_args_list]
    assert any("pg_advisory_unlock_all" in sql for sql in unlock_calls)
    lock_db.close.assert_called()


def test_run_locked_increments_skipped_and_does_not_update_success(monitor_service):
    lock_db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=False)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, lock_db)

    monitor_service.monitor_signals.assert_not_called()
    assert monitor_service.lock_acquisition_failures == 1
    assert monitor_service.skipped_cycles == 1
    assert monitor_service.last_successful_cycle_at is None
    monitor_service._release_monitor_lock.assert_called_once()
    assert monitor_service._release_monitor_lock.call_args[0][1] is False


def test_run_locked_path_does_not_leave_transaction_open(monitor_service):
    lock_db = _mock_db_session()
    lock_db.execute.return_value.scalar.return_value = False
    monitor_service.is_running = False
    monitor_service.monitor_signals = AsyncMock()

    _run_one_cycle(monitor_service, lock_db)

    monitor_service.monitor_signals.assert_not_called()
    lock_sql = str(lock_db.execute.call_args_list[0][0][0])
    assert "pg_try_advisory_lock" in lock_sql
    lock_db.rollback.assert_called_once()
    lock_db.close.assert_called_once()


def test_overlapping_cycle_skipped_before_db_advisory_lock(monitor_service):
    monitor_service.is_running = False
    monitor_service._cycle_active = True
    monitor_service._create_lock_session = Mock()
    monitor_service.monitor_signals = AsyncMock()

    async def _stop_after_sleep(_delay):
        monitor_service.is_running = False

    async def _run():
        with patch("asyncio.sleep", side_effect=_stop_after_sleep):
            await monitor_service.start()

    _run_async(_run())

    monitor_service._create_lock_session.assert_not_called()
    monitor_service.monitor_signals.assert_not_called()
    assert monitor_service.overlap_skip_count == 1


def test_successful_cycle_updates_last_successful_cycle_at(monitor_service):
    lock_db = _mock_db_session()
    work_db = _mock_db_session()
    monitor_service.is_running = False
    monitor_service._acquire_monitor_lock = Mock(return_value=True)
    monitor_service._release_monitor_lock = Mock()
    monitor_service.monitor_signals = AsyncMock()

    before = datetime.now(timezone.utc)
    _run_one_cycle(monitor_service, lock_db, work_db)

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
        mock_svc.timeout_count = 0
        mock_svc.overlap_skip_count = 0
        mock_svc.last_timeout_at = None

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
        mock_svc.timeout_count = 0
        mock_svc.overlap_skip_count = 0
        mock_svc.last_timeout_at = None

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
        mock_svc.timeout_count = 0
        mock_svc.overlap_skip_count = 0
        mock_svc.last_timeout_at = None

        result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["status"] == "PASS"
    assert result["successful_cycle_count"] == 42
    assert result["last_successful_cycle_age_minutes"] < 30


def test_health_exposes_timeout_and_skip_counters():
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock_svc:
        mock_svc.is_running = True
        mock_svc.last_run_at = datetime.now(timezone.utc)
        mock_svc.last_successful_cycle_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        mock_svc.successful_cycle_count = 10
        mock_svc.lock_acquisition_failures = 1
        mock_svc.skipped_cycles = 2
        mock_svc.timeout_count = 3
        mock_svc.overlap_skip_count = 4
        mock_svc.last_timeout_at = datetime.now(timezone.utc) - timedelta(minutes=5)

        result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["timeout_count"] == 3
    assert result["overlap_skip_count"] == 4
    assert result["status"] == "WARN"


def test_health_warn_on_recent_timeout():
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock_svc:
        mock_svc.is_running = True
        mock_svc.last_run_at = datetime.now(timezone.utc)
        mock_svc.last_successful_cycle_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        mock_svc.successful_cycle_count = 10
        mock_svc.lock_acquisition_failures = 0
        mock_svc.skipped_cycles = 0
        mock_svc.timeout_count = 1
        mock_svc.overlap_skip_count = 0
        mock_svc.last_timeout_at = datetime.now(timezone.utc) - timedelta(minutes=1)

        result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["status"] == "WARN"


def test_signal_monitor_lock_id_constant():
    assert SIGNAL_MONITOR_LOCK_ID == 123456
