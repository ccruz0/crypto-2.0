"""Tests for Jarvis Control Center Builder workflow integration (Phase 2A Step 8)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis_control import router as jarvis_control_router
from app.database import Base, ensure_jarvis_control_center_tables
from app.jarvis.control import persistence as jcp
from app.jarvis.control import workflow as wfl
from app.jarvis.control.workflow import BuilderWorkflowConflictError, validate_builder_transition
from app.models.jarvis_control_models import (
    JarvisControlApproval,
    JarvisControlAuditEvent,
    JarvisControlSession,
    JarvisControlTask,
)


def _control_app() -> FastAPI:
    fa = FastAPI()
    fa.include_router(jarvis_control_router, prefix="/api/jarvis/control")
    return fa


@pytest.fixture()
def control_db(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            JarvisControlSession.__table__,
            JarvisControlTask.__table__,
            JarvisControlApproval.__table__,
            JarvisControlAuditEvent.__table__,
        ],
    )
    monkeypatch.setattr(jcp, "engine", engine)

    def _ensure(_engine):
        return ensure_jarvis_control_center_tables(_engine)

    monkeypatch.setattr(jcp, "ensure_jarvis_control_center_tables", _ensure)
    yield engine
    engine.dispose()


def _auth_headers(monkeypatch) -> dict[str, str]:
    monkeypatch.setenv("GOVERNANCE_API_TOKEN", "jarvis-control-test-token")
    return {"Authorization": "Bearer jarvis-control-test-token"}


def _builder_env(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.delenv("ATP_TRADING_ONLY", raising=False)


def _create_builder_task(control_db, *, status: str = "queued") -> str:
    sid = jcp.create_control_session(created_by="test:workflow", environment="local")
    return jcp.create_control_task(
        session_id=sid,
        prompt="workflow test task",
        mode="builder",
        status=status,
        builder_artifact={"stub": True, "artifacts": []},
    )


def test_validate_allowed_transitions() -> None:
    validate_builder_transition("queued", "awaiting_approval")
    validate_builder_transition("awaiting_approval", "approved")
    validate_builder_transition("awaiting_approval", "rejected")


def test_validate_disallowed_transitions() -> None:
    with pytest.raises(BuilderWorkflowConflictError):
        validate_builder_transition("queued", "approved")
    with pytest.raises(BuilderWorkflowConflictError):
        validate_builder_transition("queued", "rejected")
    with pytest.raises(BuilderWorkflowConflictError):
        validate_builder_transition("approved", "rejected")
    with pytest.raises(BuilderWorkflowConflictError):
        validate_builder_transition("rejected", "approved")


def test_artifact_save_moves_queued_to_awaiting_approval(control_db) -> None:
    task_id = _create_builder_task(control_db, status="queued")
    result = wfl.save_builder_artifact(
        task_id,
        {"stub": True, "outputs": [{"type": "plan", "content": "step one"}]},
        actor_id="builder-ui",
    )
    assert result["status"] == "awaiting_approval"
    assert result["version"] >= 1

    task = jcp.get_control_task(task_id)
    assert task is not None
    assert task["status"] == "awaiting_approval"

    events = jcp.list_control_audit_events(task_id=task_id)
    assert any(e["type"] == "builder_artifact_updated" for e in events)
    artifact_event = next(e for e in events if e["type"] == "builder_artifact_updated")
    assert artifact_event["payload"]["previous_status"] == "queued"
    assert artifact_event["payload"]["new_status"] == "awaiting_approval"


def test_invalid_approve_from_queued_returns_409(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_builder_task(control_db, status="queued")
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1"},
    )
    assert r.status_code == 409


def test_full_lifecycle_queued_to_approved(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_builder_task(control_db, status="queued")
    client = TestClient(_control_app())

    artifact = client.post(
        f"/api/jarvis/control/builder/{task_id}/artifact",
        headers=_auth_headers(monkeypatch),
        json={"artifact": {"stub": True, "summary": "ready for review"}},
    )
    assert artifact.status_code == 200
    assert artifact.json()["status"] == "awaiting_approval"

    approved = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-lifecycle", "comment": "ship it"},
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"

    detail = client.get(
        f"/api/jarvis/control/builder/{task_id}",
        headers=_auth_headers(monkeypatch),
    )
    assert detail.status_code == 200
    body = detail.json()
    assert body["status"] == "approved"
    assert body["approvals_count"] == 1
    assert body["latest_approval"]["approval_status"] == "approved"
    assert body["timeline_count"] >= 2
    assert body["artifact_version"] >= 1
    assert body["artifact_updated_at"] is not None


def test_timeline_retrieval(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_builder_task(control_db, status="queued")
    client = TestClient(_control_app())

    client.post(
        f"/api/jarvis/control/builder/{task_id}/artifact",
        headers=_auth_headers(monkeypatch),
        json={"artifact": {"stub": True, "summary": "timeline test"}},
    )
    client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-timeline"},
    )

    r = client.get(
        f"/api/jarvis/control/builder/{task_id}/timeline",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["count"] == len(body["events"])
    assert body["count"] >= 2
    types = {event["type"] for event in body["events"]}
    assert "builder_artifact_updated" in types
    assert "builder_task_approved" in types

    timestamps = [event["ts"] for event in body["events"] if event.get("ts")]
    assert timestamps == sorted(timestamps, reverse=True)


def test_audit_events_emitted_for_reject_path(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_builder_task(control_db, status="awaiting_approval")
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/reject",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-reject", "comment": "not ready"},
    )
    assert r.status_code == 200

    events = jcp.list_control_audit_events(task_id=task_id)
    assert any(e["type"] == "builder_task_rejected" for e in events)
