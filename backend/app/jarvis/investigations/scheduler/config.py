"""Environment configuration for the autonomous investigation scheduler."""

from __future__ import annotations

import os
import socket
import uuid

_DEFAULT_INTERVAL_SECONDS = 900  # 15 minutes
_DEFAULT_LEADER_LEASE_SECONDS = 120


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def investigation_scheduler_enabled() -> bool:
    return _bool_env("JARVIS_INVESTIGATION_SCHEDULER_ENABLED", default=True)


def investigation_scheduler_should_autostart() -> bool:
    """True when this primary process should start the read-only scheduler loop."""
    run_poller = (os.environ.get("RUN_TELEGRAM_POLLER") or "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    return run_poller and investigation_scheduler_enabled()


def investigation_scheduler_interval_seconds() -> int:
    raw = (os.environ.get("JARVIS_INVESTIGATION_SCHEDULER_INTERVAL_SECONDS") or "").strip()
    if raw:
        try:
            return max(60, int(raw))
        except ValueError:
            pass
    return _DEFAULT_INTERVAL_SECONDS


def investigation_scheduler_leader_lease_seconds() -> int:
    raw = (os.environ.get("JARVIS_INVESTIGATION_SCHEDULER_LEADER_LEASE_SECONDS") or "").strip()
    if raw:
        try:
            return max(30, int(raw))
        except ValueError:
            pass
    return _DEFAULT_LEADER_LEASE_SECONDS


def scheduler_instance_id() -> str:
    """Stable-ish process identifier for leader election."""
    host = (socket.gethostname() or "unknown").strip()
    pid = os.getpid()
    return f"{host}:{pid}:{uuid.uuid4().hex[:8]}"


def investigation_scheduler_status() -> dict:
    from app.jarvis.investigations.scheduler.loop import get_scheduler_runtime_state

    runtime = get_scheduler_runtime_state()
    return {
        "enabled": investigation_scheduler_enabled(),
        "interval_seconds": investigation_scheduler_interval_seconds(),
        "leader_lease_seconds": investigation_scheduler_leader_lease_seconds(),
        **runtime,
    }
