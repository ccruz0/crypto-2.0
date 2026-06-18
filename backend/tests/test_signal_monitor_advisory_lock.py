"""Tests for the signal monitor advisory-lock 123456 lifecycle (PR #62).

These tests verify that advisory lock 123456 is acquired/released on a
DEDICATED, non-pooled connection (never ``SessionLocal``), that the lock is
session-scoped (no idle-in-transaction connection) and always cleaned up
(success / exception / timeout), that ``monitor_signals`` keeps receiving the
normal pooled work session, and that the health counters / health API shape do
not regress.
"""
import asyncio
import os
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from sqlalchemy.pool import NullPool

# Ensure `backend/` is importable when pytest is run from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import app.services.signal_monitor as sm
from app.services.signal_monitor import (
    SignalMonitorService,
    SIGNAL_MONITOR_LOCK_ID,
    _monitor_cycle_timeout_seconds,
)


# ---------------------------------------------------------------------------
# Fakes that emulate a PostgreSQL connection/engine without a real database.
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, scalar_value=None, rows=None):
        self._scalar = scalar_value
        self._rows = rows or []

    def scalar(self):
        return self._scalar

    def fetchall(self):
        return self._rows


class _FakeTransaction:
    def __init__(self):
        self.rolled_back = False
        self.committed = False

    def rollback(self):
        self.rolled_back = True

    def commit(self):
        self.committed = True


class _FakeConnection:
    def __init__(self, engine):
        self.engine = engine
        self.closed = False
        self.transaction = None
        self._pid_calls = 0
        self.unlocked = False

    # context-manager support for `with engine.connect() as conn:`
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    @property
    def dialect(self):
        return self.engine.dialect

    def begin(self):
        self.transaction = _FakeTransaction()
        return self.transaction

    def execute(self, clause, params=None):
        text = str(clause)
        if "pg_try_advisory_lock" in text and "xact" not in text:
            return _FakeResult(scalar_value=self.engine.acquire_result)
        if "pg_advisory_unlock" in text:
            self.unlocked = True
            return _FakeResult(scalar_value=True)
        if "pg_backend_pid" in text:
            pids = self.engine.backend_pids
            idx = min(self._pid_calls, len(pids) - 1)
            self._pid_calls += 1
            return _FakeResult(scalar_value=pids[idx])
        if "pg_locks" in text:
            return _FakeResult(rows=self.engine.lock_rows)
        return _FakeResult()

    def close(self):
        self.closed = True


class _FakeDialect:
    def __init__(self, name="postgresql"):
        self.name = name


class _FakeEngine:
    """Mimics a NullPool engine: every connect() returns a fresh connection."""

    def __init__(self, acquire_result=True, backend_pids=(4242,), dialect="postgresql", lock_rows=None):
        self.acquire_result = acquire_result
        self.backend_pids = list(backend_pids)
        self.dialect = _FakeDialect(dialect)
        self.lock_rows = lock_rows or []
        self.connections = []

    def connect(self):
        conn = _FakeConnection(self)
        self.connections.append(conn)
        return conn

    @property
    def lock_connection(self):
        """The dedicated connection on which the session lock was acquired."""
        for c in self.connections:
            if c.transaction is None and not c.closed and c._pid_calls > 0:
                return c
        # After release, find the connection that was used for acquire/unlock.
        for c in self.connections:
            if c._pid_calls > 0:
                return c
        return None


class _FakeWorkSession:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def _make_service(tmp_path=None):
    svc = SignalMonitorService()
    svc.monitor_interval = 0
    # Isolate persisted status so counters never leak across tests (or from a
    # real /tmp/signal_monitor_status.json written by production / other tests).
    import tempfile
    if tmp_path is not None:
        status_path = Path(tmp_path) / f"sm_status_{id(svc)}.json"
    else:
        fd, raw = tempfile.mkstemp(suffix=".json")
        os.close(fd)
        os.unlink(raw)
        status_path = Path(raw)
    svc.status_file_path = status_path
    svc.last_successful_cycle_at = None
    svc.successful_cycle_count = 0
    svc.lock_acquisition_failures = 0
    svc.timeout_count = 0
    svc.last_timeout_at = None
    return svc


# ---------------------------------------------------------------------------
# Timeout configuration
# ---------------------------------------------------------------------------
def test_monitor_cycle_timeout_disabled_by_default(monkeypatch):
    monkeypatch.delenv("MONITOR_CYCLE_TIMEOUT", raising=False)
    assert _monitor_cycle_timeout_seconds() == 0.0


def test_monitor_cycle_timeout_not_low_120s_by_default(monkeypatch):
    """Regression guard: do not silently default to the old 120s timeout."""
    monkeypatch.delenv("MONITOR_CYCLE_TIMEOUT", raising=False)
    assert _monitor_cycle_timeout_seconds() != 120.0


def test_monitor_cycle_timeout_respects_env(monkeypatch):
    monkeypatch.setenv("MONITOR_CYCLE_TIMEOUT", "3000")
    assert _monitor_cycle_timeout_seconds() == 3000.0
    monkeypatch.setenv("MONITOR_CYCLE_TIMEOUT", "garbage")
    assert _monitor_cycle_timeout_seconds() == 0.0


# ---------------------------------------------------------------------------
# Dedicated lock engine: NullPool, not SessionLocal
# ---------------------------------------------------------------------------
def test_lock_engine_uses_nullpool_and_is_not_session_pool(monkeypatch):
    from sqlalchemy import create_engine
    main_engine = create_engine("sqlite://")  # default (pooled) engine
    monkeypatch.setattr("app.database.engine", main_engine, raising=False)

    svc = _make_service()
    lock_engine = svc._get_lock_engine()

    assert lock_engine is not None
    assert lock_engine is not main_engine, "lock engine must be a dedicated engine"
    assert isinstance(lock_engine.pool, NullPool), "lock engine must use NullPool"
    # Cached on subsequent calls.
    assert svc._get_lock_engine() is lock_engine


def test_lock_engine_none_when_db_unavailable(monkeypatch):
    monkeypatch.setattr("app.database.engine", None, raising=False)
    svc = _make_service()
    assert svc._get_lock_engine() is None


def test_acquire_does_not_touch_session_local(monkeypatch):
    """The advisory lock must never be acquired on the SessionLocal pool."""
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(111,))
    svc = _make_service()
    svc._lock_engine = fake_engine

    session_local_mock = Mock()
    monkeypatch.setattr(sm, "SessionLocal", session_local_mock)

    lock = svc._acquire_monitor_lock("cycle-1")
    svc._release_monitor_lock(lock, "cycle-1")

    session_local_mock.assert_not_called()


# ---------------------------------------------------------------------------
# Acquire / release lifecycle (session-scoped, no open transaction)
# ---------------------------------------------------------------------------
def test_acquire_uses_session_lock_and_logs_backend_pid(monkeypatch):
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(777,))
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock = svc._acquire_monitor_lock("cycle-x")

    assert lock.acquired is True
    assert lock.backend_pid == 777
    assert svc.last_lock_backend_pid == 777
    # Dedicated connection held open without an idle-in-transaction state.
    assert lock.connection is not None
    assert lock.connection.transaction is None


def test_acquire_and_release_use_same_backend_pid():
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(500, 500))
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock = svc._acquire_monitor_lock("cycle-rel")
    conn = lock.connection

    close_pid = svc._release_monitor_lock(lock, "cycle-rel")

    assert lock.backend_pid == 500
    assert close_pid == 500, "acquire and release must use the same backend pid"
    assert conn.unlocked is True, "pg_advisory_unlock must be called on release"
    assert conn.closed is True, "dedicated lock connection must be closed (NullPool => disconnect)"


def test_release_always_closes_connection_even_when_unlock_fails():
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(600, 600))
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock = svc._acquire_monitor_lock("cycle-unlock-fail")
    conn = lock.connection

    original_execute = conn.execute

    def patched_execute(clause, params=None):
        text = str(clause)
        if "pg_advisory_unlock" in text:
            raise RuntimeError("unlock failed")
        return original_execute(clause, params)

    conn.execute = patched_execute

    close_pid = svc._release_monitor_lock(lock, "cycle-unlock-fail")

    assert close_pid == 600
    assert conn.closed is True, "connection must close in finally even if unlock fails"


def test_acquire_does_not_begin_transaction():
    """Session lock must not open a transaction (no idle-in-transaction backend)."""
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(888,))
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock = svc._acquire_monitor_lock("cycle-no-tx")
    assert lock.acquired is True
    assert lock.connection.transaction is None
    svc._release_monitor_lock(lock, "cycle-no-tx")


def test_acquire_when_held_elsewhere_closes_probe_connection():
    fake_engine = _FakeEngine(acquire_result=False, backend_pids=(900,))
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock = svc._acquire_monitor_lock("cycle-locked")

    assert lock.acquired is False
    assert lock.connection is None, "non-acquired lock should not retain a connection"
    # The probe connection that was opened must have been closed.
    assert fake_engine.connections[0].closed is True


def test_release_is_safe_on_non_acquired_lock():
    svc = _make_service()
    # _MonitorLock with no connection (e.g. lock held elsewhere / no engine).
    lock = sm._MonitorLock(acquired=False)
    assert svc._release_monitor_lock(lock, "cid") is None


def test_next_acquire_not_blocked_after_release():
    """After release, a brand-new connection is used and acquire succeeds again."""
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(1, 2, 3, 4))
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock1 = svc._acquire_monitor_lock("c1")
    conn1 = lock1.connection
    svc._release_monitor_lock(lock1, "c1")
    assert conn1.closed is True

    lock2 = svc._acquire_monitor_lock("c2")
    assert lock2.acquired is True
    assert lock2.connection is not conn1, "must use a fresh dedicated connection"
    svc._release_monitor_lock(lock2, "c2")
    assert lock2.connection.closed is True


def test_non_postgres_dialect_treated_as_acquired_without_real_lock():
    fake_engine = _FakeEngine(acquire_result=True, dialect="sqlite")
    svc = _make_service()
    svc._lock_engine = fake_engine

    lock = svc._acquire_monitor_lock("c-sqlite")
    assert lock.acquired is True
    assert lock.connection is None, "non-postgres path does not retain a lock connection"
    # Connection was closed immediately (no lock to hold).
    assert fake_engine.connections[0].closed is True


# ---------------------------------------------------------------------------
# Full-cycle integration-style tests via start() (one cycle).
# ---------------------------------------------------------------------------
def _run_one_cycle(svc, fake_engine, monitor_coro_factory, monkeypatch):
    """Run exactly one cycle of start() with a fake lock engine + work session."""
    svc._lock_engine = fake_engine
    work_session = _FakeWorkSession()
    monkeypatch.setattr(sm, "SessionLocal", lambda: work_session)

    received = {}

    async def fake_monitor(db):
        received["db"] = db
        return await monitor_coro_factory()

    svc.monitor_signals = fake_monitor

    # Always stop the loop after the (guaranteed) release path runs once.
    orig_release = svc._release_monitor_lock

    def release_and_stop(lock, cid):
        res = orig_release(lock, cid)
        svc.is_running = False
        return res

    svc._release_monitor_lock = release_and_stop

    async def _bounded():
        # Safety net: one cycle must finish quickly; never hang the suite.
        await asyncio.wait_for(svc.start(), timeout=10)

    asyncio.run(_bounded())
    return received, work_session


def test_cycle_success_runs_monitor_on_work_session_and_releases(monkeypatch):
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(321,))
    svc = _make_service()

    async def ok():
        return None

    received, work_session = _run_one_cycle(svc, fake_engine, ok, monkeypatch)

    # monitor_signals received the normal pooled work session, not the lock conn.
    assert received["db"] is work_session
    assert work_session.committed is True
    assert work_session.closed is True
    # Lock connection cleaned up (unlock + close; no transaction held open).
    lock_conn = fake_engine.lock_connection
    assert lock_conn is not None
    assert lock_conn.closed is True
    assert lock_conn.unlocked is True
    assert lock_conn.transaction is None, "must not hold idle-in-transaction lock connection"
    # Counters.
    assert svc.successful_cycle_count == 1
    assert svc.timeout_count == 0
    assert svc.last_successful_cycle_at is not None


def test_cycle_exception_still_releases_lock(monkeypatch):
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(55,))
    svc = _make_service()

    async def boom():
        raise ValueError("monitor blew up")

    received, work_session = _run_one_cycle(svc, fake_engine, boom, monkeypatch)

    assert received["db"] is work_session
    assert work_session.rolled_back is True
    assert work_session.closed is True
    # Lock still released/closed despite the exception.
    lock_conn = fake_engine.lock_connection
    assert lock_conn.closed is True
    assert lock_conn.unlocked is True
    assert lock_conn.transaction is None
    assert svc.successful_cycle_count == 0


def test_cycle_timeout_still_releases_lock(monkeypatch):
    fake_engine = _FakeEngine(acquire_result=True, backend_pids=(99,))
    svc = _make_service()
    # Enable a short hard timeout via env (start() re-reads MONITOR_CYCLE_TIMEOUT).
    monkeypatch.setenv("MONITOR_CYCLE_TIMEOUT", "0.05")

    async def hang():
        # Block "forever"; asyncio.wait_for will cancel this after the timeout.
        await asyncio.Event().wait()

    received, work_session = _run_one_cycle(svc, fake_engine, hang, monkeypatch)

    assert svc.timeout_count == 1
    assert svc.last_timeout_at is not None
    assert svc.successful_cycle_count == 0
    # Work session rolled back + closed; lock released/closed even on timeout.
    assert work_session.rolled_back is True
    assert work_session.closed is True
    lock_conn = fake_engine.lock_connection
    assert lock_conn.closed is True
    assert lock_conn.unlocked is True
    assert lock_conn.transaction is None


def test_cycle_run_locked_increments_counter_and_does_not_run_monitor(monkeypatch):
    fake_engine = _FakeEngine(acquire_result=False, backend_pids=(0,))
    svc = _make_service()

    async def should_not_run():  # pragma: no cover - must never be awaited
        raise AssertionError("monitor_signals must not run when lock not acquired")

    received, work_session = _run_one_cycle(svc, fake_engine, should_not_run, monkeypatch)

    assert "db" not in received
    assert svc.lock_acquisition_failures == 1
    assert svc.successful_cycle_count == 0
    assert work_session.committed is False


# ---------------------------------------------------------------------------
# Health counters / API shape
# ---------------------------------------------------------------------------
def test_signal_monitor_health_exposes_diagnostic_counters():
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock:
        mock.is_running = True
        mock.last_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        mock.last_successful_cycle_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        mock.successful_cycle_count = 7
        mock.timeout_count = 0
        mock.lock_acquisition_failures = 2
        mock.last_lock_backend_pid = 4242
        with patch.dict("os.environ", {"RUN_SIGNAL_MONITOR": "true"}, clear=False):
            result = _check_signal_monitor_health(stale_threshold_minutes=30)

    # Existing shape preserved.
    assert result["status"] == "PASS"
    assert result["is_running"] is True
    assert "last_cycle_age_minutes" in result
    # New diagnostic fields present.
    assert result["successful_cycle_count"] == 7
    assert result["timeout_count"] == 0
    assert result["run_locked_count"] == 2
    assert result["last_lock_backend_pid"] == 4242
    assert "last_successful_cycle_age_minutes" in result


def test_signal_monitor_health_no_crash_without_new_attributes():
    """A bare mock (no counters) must not break health (no API regression)."""
    from app.services.system_health import _check_signal_monitor_health

    with patch("app.services.system_health.signal_monitor_service") as mock:
        # Use a spec-less mock but explicitly remove the new attributes so
        # getattr(..., default) is exercised.
        mock.is_running = True
        mock.last_run_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        for attr in (
            "last_successful_cycle_at",
            "successful_cycle_count",
            "timeout_count",
            "lock_acquisition_failures",
            "last_lock_backend_pid",
        ):
            setattr(mock, attr, None)
        with patch.dict("os.environ", {"RUN_SIGNAL_MONITOR": "true"}, clear=False):
            result = _check_signal_monitor_health(stale_threshold_minutes=30)

    assert result["status"] in ("PASS", "WARN", "FAIL")
    assert result["successful_cycle_count"] is None
    assert result["timeout_count"] is None


def test_lock_id_constant_is_123456():
    assert SIGNAL_MONITOR_LOCK_ID == 123456
