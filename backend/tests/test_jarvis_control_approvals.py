"""Tests for Jarvis Control Center Builder approval layer (Phase 2A Step 7)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis_control import router as jarvis_control_router
from app.database import Base, ensure_jarvis_control_center_tables
from app.jarvis.control import persistence as jcp
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


def _create_awaiting_builder_task(control_db, *, status: str = "awaiting_approval") -> str:
    sid = jcp.create_control_session(created_by="test:approvals", environment="local")
    return jcp.create_control_task(
        session_id=sid,
        prompt="approval test task",
        mode="builder",
        status=status,
        builder_artifact={"stub": True, "artifacts": []},
    )


def test_approve_success(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1", "comment": "looks good"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["status"] == "approved"
    assert body["approval"]["approval_status"] == "approved"
    assert body["approval"]["approved_by"] == "reviewer-1"
    assert body["approval"]["comment"] == "looks good"

    task = jcp.get_control_task(task_id)
    assert task is not None
    assert task["status"] == "approved"
    assert task["completed_at"] is not None

    approvals = jcp.get_control_approvals(task_id)
    assert len(approvals) == 1
    assert approvals[0]["approval_status"] == "approved"


def test_reject_success(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/reject",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-2", "comment": "needs changes"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "rejected"
    assert body["approval"]["approval_status"] == "rejected"
    assert body["approval"]["comment"] == "needs changes"

    task = jcp.get_control_task(task_id)
    assert task is not None
    assert task["status"] == "rejected"


def test_duplicate_approve_rejected(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    first = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1"},
    )
    assert second.status_code == 409


def test_duplicate_reject_rejected(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    first = client.post(
        f"/api/jarvis/control/builder/{task_id}/reject",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-2"},
    )
    assert first.status_code == 200

    second = client.post(
        f"/api/jarvis/control/builder/{task_id}/reject",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-2"},
    )
    assert second.status_code == 409


def test_invalid_transition_returns_409(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db, status="queued")
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1"},
    )
    assert r.status_code == 409


def test_missing_task_returns_404(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/jcc-missing/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1"},
    )
    assert r.status_code == 404


def test_trading_only_returns_403(control_db, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-1"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "builder_approval_blocked_trading_only"


def test_audit_event_recorded_on_approve(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-audit", "comment": "ship it"},
    )
    assert r.status_code == 200

    events = jcp.list_control_audit_events(task_id=task_id)
    assert any(e["type"] == "builder_task_approved" for e in events)
    approved = next(e for e in events if e["type"] == "builder_task_approved")
    assert approved["actor_id"] == "reviewer-audit"
    assert approved["payload"]["comment"] == "ship it"
    assert approved["payload"]["new_status"] == "approved"


def test_audit_event_recorded_on_reject(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/reject",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-reject", "comment": "not yet"},
    )
    assert r.status_code == 200

    events = jcp.list_control_audit_events(task_id=task_id)
    assert any(e["type"] == "builder_task_rejected" for e in events)
    rejected = next(e for e in events if e["type"] == "builder_task_rejected")
    assert rejected["actor_id"] == "reviewer-reject"
    assert rejected["payload"]["new_status"] == "rejected"


def test_list_approvals_via_get(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_awaiting_builder_task(control_db)
    client = TestClient(_control_app())
    approved = client.post(
        f"/api/jarvis/control/builder/{task_id}/approve",
        headers=_auth_headers(monkeypatch),
        json={"actor_id": "reviewer-list"},
    )
    assert approved.status_code == 200

    r = client.get(
        f"/api/jarvis/control/builder/{task_id}/approvals",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["count"] == 1
    assert body["approvals"][0]["approved_by"] == "reviewer-list"
