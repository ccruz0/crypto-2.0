"""
Jarvis Control Center API — read-only status, task visibility, Builder prepare stub.

Auth: Bearer GOVERNANCE_API_TOKEN if set, else OPENCLAW_API_TOKEN (same as governance routes).
Mounted only when JARVIS_CONTROL_ENABLED=1 (see factory.py).
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.api.routes_governance import _verify_governance_token
from app.core.environment import (
    is_atp_trading_only,
    is_jarvis_builder_allowed,
    is_jarvis_control_enabled,
)
from app.jarvis.control import artifacts as builder_artifacts
from app.jarvis.control.artifacts import BuilderArtifactError
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


class BuilderPrepareRequest(BaseModel):
    prompt: str = Field(..., min_length=1, description="Builder task prompt")
    domain: str | None = Field(default="software", description="Control domain (default software)")
    requested_by: str = Field(default="dashboard", description="Requesting user or surface")


class BuilderArtifactUpdateRequest(BaseModel):
    artifact: dict[str, Any] = Field(..., description="Builder artifact JSON object")


def _require_builder_prepare_allowed() -> None:
    if is_atp_trading_only():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "builder_blocked_trading_only",
                "message": "Builder prepare is blocked when ATP_TRADING_ONLY=1.",
            },
        )
    if not is_jarvis_builder_allowed():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "builder_not_allowed",
                "message": "Builder prepare is disabled (set JARVIS_BUILDER_ALLOWED=1 on non-trading hosts).",
            },
        )


def _require_builder_artifact_write_allowed() -> None:
    if is_atp_trading_only():
        raise HTTPException(
            status_code=403,
            detail={
                "error": "builder_artifact_blocked_trading_only",
                "message": "Builder artifact writes are blocked when ATP_TRADING_ONLY=1.",
            },
        )


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


@router.post("/builder/prepare")
def builder_prepare_stub(
    body: BuilderPrepareRequest,
    _auth: None = Depends(_verify_governance_token),
    _builder: None = Depends(_require_builder_prepare_allowed),
) -> dict[str, Any]:
    return _service.prepare_builder_stub(
        prompt=body.prompt,
        domain=body.domain or "software",
        requested_by=body.requested_by or "dashboard",
    )


@router.get("/builder/{task_id}/artifact")
def builder_get_artifact(
    task_id: str,
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    detail = builder_artifacts.get_builder_artifact(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Builder task not found: {task_id}")
    return detail


@router.post("/builder/{task_id}/artifact")
def builder_save_artifact(
    task_id: str,
    body: BuilderArtifactUpdateRequest,
    _auth: None = Depends(_verify_governance_token),
    _write: None = Depends(_require_builder_artifact_write_allowed),
) -> dict[str, Any]:
    try:
        return builder_artifacts.save_builder_artifact(task_id, body.artifact)
    except BuilderArtifactError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except builder_artifacts.BuilderArtifactNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/builder/{task_id}")
def builder_task_detail(
    task_id: str,
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    detail = _service.get_builder_task(task_id)
    if detail is None:
        raise HTTPException(status_code=404, detail=f"Builder task not found: {task_id}")
    return detail
