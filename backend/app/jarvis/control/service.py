"""Jarvis Control Center service layer (read-only status; no Builder execution)."""

from __future__ import annotations

from typing import Any

from app.core.environment import (
    getRuntimeEnv,
    is_atp_trading_only,
    is_jarvis_builder_allowed,
    is_jarvis_control_enabled,
)
from app.jarvis.control import persistence as jcp


class JarvisControlService:
    """Read-only control surface over persistence and environment gates."""

    def get_control_status(self) -> dict[str, Any]:
        control_enabled = is_jarvis_control_enabled()
        builder_allowed = is_jarvis_builder_allowed()
        trading_only = is_atp_trading_only()
        environment = getRuntimeEnv()
        builder_available = control_enabled and builder_allowed and not trading_only
        return {
            "control_enabled": control_enabled,
            "builder_allowed": builder_allowed,
            "trading_only": trading_only,
            "environment": environment,
            "builder_available": builder_available,
        }

    def list_recent_tasks(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return jcp.list_control_tasks(limit=limit)

    def get_task_detail(self, task_id: str) -> dict[str, Any] | None:
        return jcp.get_control_task(task_id)
