"""
Jarvis Control Center API — read-only status and task visibility.

Auth: Bearer GOVERNANCE_API_TOKEN if set, else OPENCLAW_API_TOKEN (same as governance routes).
Mounted only when JARVIS_CONTROL_ENABLED=1 (see factory.py).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.routes_governance import _verify_governance_token
from app.core.environment import is_jarvis_control_enabled
from app.jarvis.control.service import JarvisControlService

logger = logging.getLogger(__name__)

_service = JarvisControlService()


def _require_jarvis_control_enabled() -> None:
    if not is_jarvis_control_enabled():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "jarvis_control_disabled",
                "message": "Jarvis Control Center is disabled (set JARVIS_CONTROL_ENABLED=1).",
            },
        )


router = APIRouter(dependencies=[Depends(_require_jarvis_control_enabled)])


@router.get("/status")
def jarvis_control_status(
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    return _service.get_control_status()


@router.get("/tasks")
def jarvis_control_list_tasks(
    limit: int = Query(20, ge=1, le=100),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    tasks = _service.list_recent_tasks(limit=limit)
    return {"tasks": tasks, "count": len(tasks)}


@router.get("/tasks/{task_id}")
def jarvis_control_task_detail(
    task_id: str,
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    detail = _service.get_task_detail(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Control task not found: {task_id}")
    return detail
