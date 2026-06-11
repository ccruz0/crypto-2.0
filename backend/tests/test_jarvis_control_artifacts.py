"""Tests for Jarvis Control Center Builder artifact layer (Phase 2A Step 6)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis_control import router as jarvis_control_router
from app.database import Base, ensure_jarvis_control_center_tables
from app.jarvis.control import artifacts as builder_artifacts
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


def _create_builder_task(control_db) -> str:
    sid = jcp.create_control_session(created_by="test:artifacts", environment="local")
    return jcp.create_control_task(
        session_id=sid,
        prompt="artifact test task",
        mode="builder",
        builder_artifact={"stub": True, "artifacts": []},
    )


def test_create_artifact_via_post(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_builder_task(control_db)
    client = TestClient(_control_app())
    payload = {
        "artifact": {
            "stub": True,
            "outputs": [{"type": "plan", "content": "step one"}],
        }
    }
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/artifact",
        headers=_auth_headers(monkeypatch),
        json=payload,
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["artifact"]["outputs"][0]["content"] == "step one"
    assert body["version"] == 2
    assert body["updated_at"] is not None


def test_update_artifact_via_service(control_db) -> None:
    task_id = _create_builder_task(control_db)
    saved = builder_artifacts.save_builder_artifact(
        task_id,
        {"stub": True, "outputs": [{"type": "note", "content": "initial"}]},
    )
    assert saved["version"] == 2

    updated = builder_artifacts.update_builder_artifact(
        task_id,
        {"outputs": [{"type": "note", "content": "merged"}]},
    )
    assert updated["version"] == 3
    assert updated["artifact"]["stub"] is True
    assert updated["artifact"]["outputs"][0]["content"] == "merged"


def test_retrieve_artifact_via_get(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    task_id = _create_builder_task(control_db)
    builder_artifacts.save_builder_artifact(
        task_id,
        {"stub": True, "summary": "ready for review"},
    )
    client = TestClient(_control_app())
    r = client.get(
        f"/api/jarvis/control/builder/{task_id}/artifact",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == task_id
    assert body["artifact"]["summary"] == "ready for review"
    assert body["version"] == 2
    assert body["updated_at"] is not None


def test_missing_task_returns_404(control_db, monkeypatch) -> None:
    _builder_env(monkeypatch)
    client = TestClient(_control_app())
    r = client.get(
        "/api/jarvis/control/builder/jcc-missing/artifact",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 404


def test_artifact_post_blocked_when_trading_only(control_db, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.delenv("JARVIS_BUILDER_ALLOWED", raising=False)
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    task_id = _create_builder_task(control_db)
    client = TestClient(_control_app())
    r = client.post(
        f"/api/jarvis/control/builder/{task_id}/artifact",
        headers=_auth_headers(monkeypatch),
        json={"artifact": {"stub": True}},
    )
    assert r.status_code == 403
    assert r.json()["detail"]["error"] == "builder_artifact_blocked_trading_only"


def test_artifact_routes_disabled_when_control_off(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_CONTROL_ENABLED", raising=False)
    client = TestClient(_control_app())
    r = client.get(
        "/api/jarvis/control/builder/jcc-any/artifact",
        headers=_auth_headers(monkeypatch),
    )
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "jarvis_control_disabled"
