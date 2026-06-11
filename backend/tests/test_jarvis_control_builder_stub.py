"""Tests for Jarvis Control Center Builder prepare stub (Phase 2A Step 3)."""

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


def test_builder_prepare_disabled_when_control_off(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_CONTROL_ENABLED", raising=False)
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": "add logging middleware"},
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "jarvis_control_disabled"


def test_builder_prepare_blocked_when_trading_only(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": "add logging middleware"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "builder_blocked_trading_only"


def test_builder_prepare_blocked_when_builder_not_allowed(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.delenv("JARVIS_BUILDER_ALLOWED", raising=False)
    monkeypatch.delenv("ATP_TRADING_ONLY", raising=False)
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": "add logging middleware"},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "builder_not_allowed"


def test_builder_prepare_creates_stub_task(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": "add structured logging to the backend service"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "builder"
    assert body["status"] == "queued"
    assert body["stub"] is True
    assert body["risk_level"] in ("low", "medium", "high")
    assert body["message"] == "Builder task created in stub mode. No execution occurred."
    assert body["task_id"].startswith("jcc-")


def test_builder_prepare_task_has_stub_artifact(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": "summarize dashboard health"},
    )
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    detail = jcp.get_control_task(task_id)
    assert detail is not None
    assert detail["mode"] == "builder"
    assert detail["domain"] == "software"
    assert detail["status"] == "queued"
    assert detail["dry_run"] is True
    artifact = detail["builder_artifact"]
    assert artifact["stub"] is True
    assert artifact["bridge_invoked"] is False
    assert artifact["governance_created"] is False
    assert "Cursor bridge not invoked" in artifact["message"]
    assert artifact["plan"]["summary"] == "summarize dashboard health"
    assert artifact["plan"]["domain"] == "software"
    assert artifact["plan"]["risk_level"] in ("low", "medium", "high")
    assert artifact["artifacts"] == []
    assert artifact["next_action"] == "awaiting_builder_execution"
    assert detail["artifact_version"] == 1
    assert detail["artifact_updated_at"] is not None


def test_builder_prepare_creates_audit_event(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    prompt = "propose config changes to runtime env"
    client = TestClient(_control_app())
    r = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": prompt, "requested_by": "dashboard"},
    )
    assert r.status_code == 200
    task_id = r.json()["task_id"]
    events = jcp.list_control_audit_events(task_id=task_id)
    assert len(events) == 1
    event = events[0]
    assert event["type"] == "builder_prepare_stub_created"
    assert event["actor_id"] == "dashboard"
    assert event["task_id"] == task_id
    payload = event["payload"]
    assert payload["prompt_summary"] == prompt
    assert payload["stub"] is True
    assert payload["bridge_invoked"] is False
    assert payload["governance_created"] is False
    assert payload["trading_only"] is False
    assert payload["builder_allowed"] is True


def test_builder_get_task_returns_detail(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    client = TestClient(_control_app())
    created = client.post(
        "/api/jarvis/control/builder/prepare",
        headers=_auth_headers(monkeypatch),
        json={"prompt": "read runtime status for the backend"},
    )
    assert created.status_code == 200
    task_id = created.json()["task_id"]

    r = client.get(
        f"/api/jarvis/control/builder/{task_id}",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["mode"] == "builder"
    assert body["prompt"] == "read runtime status for the backend"
    assert body["builder_artifact"]["stub"] is True


def test_builder_get_task_not_found_for_advisor_task(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    sid = jcp.create_control_session(created_by="test:builder", environment="local")
    tid = jcp.create_control_task(session_id=sid, prompt="advisor only", mode="advisor")

    client = TestClient(_control_app())
    r = client.get(
        f"/api/jarvis/control/builder/{tid}",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 404
