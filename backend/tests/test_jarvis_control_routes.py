"""Tests for Jarvis Control Center read-only API (Phase 2A Step 2)."""

from __future__ import annotations

from unittest.mock import patch

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


def test_control_status_builder_available_false_by_default(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    client = TestClient(_control_app())
    r = client.get("/api/jarvis/control/status", headers=_auth_headers(monkeypatch))
    assert r.status_code == 200
    body = r.json()
    assert body["control_enabled"] is True
    assert body["builder_allowed"] is False
    assert body["trading_only"] is False
    assert body["builder_available"] is False
    assert body["environment"] in ("local", "aws")


def test_control_status_trading_only_blocks_builder_availability(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    client = TestClient(_control_app())
    r = client.get("/api/jarvis/control/status", headers=_auth_headers(monkeypatch))
    assert r.status_code == 200
    body = r.json()
    assert body["trading_only"] is True
    assert body["builder_allowed"] is False
    assert body["builder_available"] is False


def test_control_status_builder_available_when_all_gates_open(monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.delenv("ATP_TRADING_ONLY", raising=False)
    client = TestClient(_control_app())
    r = client.get("/api/jarvis/control/status", headers=_auth_headers(monkeypatch))
    assert r.status_code == 200
    body = r.json()
    assert body["builder_available"] is True


def test_control_routes_disabled_when_control_off(monkeypatch) -> None:
    monkeypatch.delenv("JARVIS_CONTROL_ENABLED", raising=False)
    client = TestClient(_control_app())
    r = client.get("/api/jarvis/control/status", headers=_auth_headers(monkeypatch))
    assert r.status_code == 404
    assert r.json()["detail"]["error"] == "jarvis_control_disabled"


def test_control_list_tasks(control_db, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    sid = jcp.create_control_session(created_by="test:routes", environment="local")
    tid = jcp.create_control_task(session_id=sid, prompt="route test task", mode="advisor")

    client = TestClient(_control_app())
    r = client.get("/api/jarvis/control/tasks", headers=_auth_headers(monkeypatch))
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["tasks"][0]["task_id"] == tid
    assert body["tasks"][0]["session_id"] == sid


def test_control_task_detail(control_db, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    sid = jcp.create_control_session(created_by="test:routes", environment="local")
    tid = jcp.create_control_task(session_id=sid, prompt="detail probe", mode="builder")

    client = TestClient(_control_app())
    r = client.get(f"/api/jarvis/control/tasks/{tid}", headers=_auth_headers(monkeypatch))
    assert r.status_code == 200
    body = r.json()
    assert body["task_id"] == tid
    assert body["prompt"] == "detail probe"
    assert body["mode"] == "builder"


def test_control_task_detail_not_found(control_db, monkeypatch) -> None:
    monkeypatch.setenv("JARVIS_CONTROL_ENABLED", "1")
    client = TestClient(_control_app())
    r = client.get("/api/jarvis/control/tasks/jcc-missing", headers=_auth_headers(monkeypatch))
    assert r.status_code == 404


def test_jarvis_advisor_routes_still_import() -> None:
    from app.api.routes_jarvis import router

    assert router is not None


def test_factory_still_imports_without_control_enabled() -> None:
    with patch.dict("os.environ", {}, clear=True):
        from app.factory import create_app

        app = create_app()
        assert app is not None
