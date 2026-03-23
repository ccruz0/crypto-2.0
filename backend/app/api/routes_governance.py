"""
Governance API: tasks, manifests, approvals, governed execution.

Auth: Bearer GOVERNANCE_API_TOKEN if set, else OPENCLAW_API_TOKEN (same pattern as /api/agent).
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_governance_token(authorization: str | None = Header(None)) -> None:
    tok = (
        (settings.GOVERNANCE_API_TOKEN or "").strip()
        or (os.environ.get("GOVERNANCE_API_TOKEN") or "").strip()
        or (settings.OPENCLAW_API_TOKEN or "").strip()
        or (os.environ.get("OPENCLAW_API_TOKEN") or "").strip()
    )
    if not tok:
        raise HTTPException(
            status_code=503,
            detail="Governance API not configured (set GOVERNANCE_API_TOKEN or OPENCLAW_API_TOKEN)",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    if authorization[7:].strip() != tok:
        raise HTTPException(status_code=403, detail="Invalid token")


class CreateTaskBody(BaseModel):
    task_id: str | None = None
    source_type: str = "manual"
    source_ref: str | None = None
    risk_level: str = "medium"
    title: str | None = None
    actor_id: str | None = "api"


class TransitionBody(BaseModel):
    to_state: str = Field(..., description="Target lifecycle state")
    actor_type: str = "human"
    actor_id: str | None = None
    reason: str | None = None


class ManifestBody(BaseModel):
    commands: list[dict[str, Any]]
    scope_summary: str = ""
    risk_level: str = "medium"
    actor_type: str = "agent"
    actor_id: str | None = None
    environment: str = "lab"
    attach_and_await_approval: bool = True


class ApproveBody(BaseModel):
    approved_by: str
    actor_id: str | None = None


class DenyBody(BaseModel):
    denied_by: str
    reason: str | None = None


class ExecuteBody(BaseModel):
    task_id: str
    manifest_id: str
    actor_id: str | None = "api"


@router.post("/governance/tasks")
def governance_create_task(
    body: CreateTaskBody,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_service import create_governance_task

    tid, row = create_governance_task(
        db,
        task_id=body.task_id,
        source_type=body.source_type,
        source_ref=body.source_ref,
        risk_level=body.risk_level,
        title=body.title,
        actor_type="human",
        actor_id=body.actor_id,
        environment="prod",
    )
    db.commit()
    return {"ok": True, "task_id": tid, "status": row.status}


@router.get("/governance/tasks/{task_id}")
def governance_get_task(
    task_id: str,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.models.governance_models import GovernanceTask

    row = db.query(GovernanceTask).filter(GovernanceTask.task_id == task_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    return {
        "task_id": row.task_id,
        "status": row.status,
        "risk_level": row.risk_level,
        "source_type": row.source_type,
        "source_ref": row.source_ref,
        "current_manifest_id": row.current_manifest_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.post("/governance/tasks/{task_id}/transition")
def governance_transition(
    task_id: str,
    body: TransitionBody,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_service import transition_task_state

    try:
        transition_task_state(
            db,
            task_id=task_id,
            to_state=body.to_state,
            actor_type=body.actor_type,
            actor_id=body.actor_id,
            environment="prod",
            reason=body.reason,
            send_telegram=True,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    return {"ok": True, "task_id": task_id, "to_state": body.to_state}


@router.post("/governance/tasks/{task_id}/manifests")
def governance_create_manifest(
    task_id: str,
    body: ManifestBody,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_service import create_manifest

    try:
        mid, row = create_manifest(
            db,
            task_id=task_id,
            commands=body.commands,
            scope_summary=body.scope_summary,
            risk_level=body.risk_level,
            actor_type=body.actor_type,
            actor_id=body.actor_id,
            environment=body.environment,
            attach_and_await_approval=body.attach_and_await_approval,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    return {"ok": True, "manifest_id": mid, "digest": row.digest, "approval_status": row.approval_status}


@router.post("/governance/manifests/{manifest_id}/approve")
def governance_approve_manifest(
    manifest_id: str,
    body: ApproveBody,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_service import approve_manifest

    try:
        approve_manifest(
            db,
            manifest_id=manifest_id,
            approved_by=body.approved_by,
            actor_type="human",
            actor_id=body.actor_id or body.approved_by,
            environment="prod",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    db.commit()
    return {"ok": True, "manifest_id": manifest_id, "status": "approved"}


@router.post("/governance/manifests/{manifest_id}/deny")
def governance_deny_manifest(
    manifest_id: str,
    body: DenyBody,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_service import deny_manifest

    deny_manifest(
        db,
        manifest_id=manifest_id,
        denied_by=body.denied_by,
        reason=body.reason,
        actor_type="human",
        actor_id=body.denied_by,
        environment="prod",
    )
    db.commit()
    return {"ok": True, "manifest_id": manifest_id, "status": "denied"}


@router.post("/governance/execute")
def governance_execute(
    body: ExecuteBody,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_executor import execute_governed_manifest

    result = execute_governed_manifest(
        db,
        task_id=body.task_id,
        manifest_id=body.manifest_id,
        actor_type="human",
        actor_id=body.actor_id or "api",
    )
    db.commit()
    # Always return structured body; audit rows are committed even on failure.
    return {"ok": bool(result.get("success")), **result}


@router.get("/governance/tasks/{task_id}/events")
def governance_list_events(
    task_id: str,
    limit: int = 100,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.models.governance_models import GovernanceEvent

    q = (
        db.query(GovernanceEvent)
        .filter(GovernanceEvent.task_id == task_id)
        .order_by(GovernanceEvent.ts.desc())
        .limit(min(max(limit, 1), 500))
    )
    rows = q.all()
    events = []
    for r in rows:
        try:
            payload = json.loads(r.payload_json or "{}")
        except json.JSONDecodeError:
            payload = {}
        events.append(
            {
                "event_id": r.event_id,
                "ts": r.ts.isoformat() if r.ts else None,
                "type": r.type,
                "actor_type": r.actor_type,
                "actor_id": r.actor_id,
                "environment": r.environment,
                "payload": payload,
            }
        )
    return {"task_id": task_id, "events": events}


@router.get("/governance/tasks/{task_id}/timeline")
def governance_task_timeline(
    task_id: str,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    """Read-only merged timeline for one governance task (DB read model only)."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_timeline import build_governance_timeline

    body = build_governance_timeline(db, task_id)
    if not body:
        raise HTTPException(status_code=404, detail="governance task not found")
    return body


@router.get("/governance/resolve")
def governance_resolve(
    task_id: str | None = None,
    notion_page_id: str | None = None,
    manifest_id: str | None = None,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    """
    Read-only: resolve exactly one of task_id (governance_tasks.task_id), notion_page_id,
    or manifest_id to ids, status, manifest hints, and timeline path(s).
    """
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_resolve import resolve_governance_task

    g = (task_id or "").strip() or None
    n = (notion_page_id or "").strip() or None
    m = (manifest_id or "").strip() or None
    if sum(1 for x in (g, n, m) if x) != 1:
        raise HTTPException(
            status_code=400,
            detail="Provide exactly one query param: task_id, notion_page_id, or manifest_id",
        )
    try:
        body = resolve_governance_task(
            db,
            governance_task_id=g,
            notion_page_id=n,
            manifest_id=m,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    if not body:
        raise HTTPException(status_code=404, detail="not found")
    return body


@router.get("/governance/by-notion/{page_id}/timeline")
def governance_timeline_by_notion(
    page_id: str,
    db: Session = Depends(get_db),
    _auth: None = Depends(_verify_governance_token),
) -> dict[str, Any]:
    """Read-only timeline for ``gov-notion-<page_id>`` (404 if governance task row missing)."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.services.governance_timeline import build_governance_timeline_for_notion

    body = build_governance_timeline_for_notion(db, page_id)
    if not body:
        raise HTTPException(
            status_code=404,
            detail="governance task not found for this Notion page (no gov-notion-<page_id> row yet)",
        )
    return body
