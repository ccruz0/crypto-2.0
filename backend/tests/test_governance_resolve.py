"""Governance resolve endpoint and trace helpers (Phase 2 control-plane usability)."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes_governance import router as governance_router
from app.database import Base, get_db
from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask
from app.services.governance_refs import (
    agent_approval_governance_note_lines,
    append_governance_telegram_trace,
    timeline_path_by_governance_task_id,
    timeline_paths_and_urls,
)
from app.services.governance_resolve import resolve_governance_task
from app.services.governance_service import create_governance_task, create_manifest
from app.services.governance_telegram import send_governance_telegram_summary


@pytest.fixture()
def resolve_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GovernanceTask.__table__,
            GovernanceManifest.__table__,
            GovernanceEvent.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def _resolve_app():
    fa = FastAPI()
    fa.include_router(governance_router, prefix="/api")
    return fa


def test_resolve_by_governance_task_id(resolve_db):
    gid = "gov-notion-resolve-1"
    create_governance_task(
        resolve_db,
        task_id=gid,
        actor_type="test",
        actor_id="t",
        environment="lab",
    )
    resolve_db.commit()
    out = resolve_governance_task(resolve_db, governance_task_id=gid)
    assert out
    assert out["governance_task_id"] == gid
    assert out["notion_page_id"] == "resolve-1"
    assert out["current_status"] == "requested"
    assert out["timeline_by_task_path"] == f"/api/governance/tasks/{gid}/timeline"
    assert out["timeline_by_notion_path"] == "/api/governance/by-notion/resolve-1/timeline"


def test_resolve_by_notion_page_id(resolve_db):
    np = "page-abc"
    gid = f"gov-notion-{np}"
    create_governance_task(
        resolve_db,
        task_id=gid,
        actor_type="test",
        actor_id="t",
        environment="lab",
    )
    resolve_db.commit()
    out = resolve_governance_task(resolve_db, notion_page_id=np)
    assert out["governance_task_id"] == gid
    assert out["notion_page_id"] == np


def test_resolve_by_manifest_id(resolve_db):
    gid = "gov-manifest-resolve"
    create_governance_task(
        resolve_db,
        task_id=gid,
        actor_type="test",
        actor_id="t",
        environment="lab",
    )
    mid, _ = create_manifest(
        resolve_db,
        task_id=gid,
        commands=[{"type": "noop"}],
        scope_summary="s",
        risk_level="low",
        actor_type="test",
        actor_id="t",
        environment="lab",
        attach_and_await_approval=False,
    )
    resolve_db.commit()
    out = resolve_governance_task(resolve_db, manifest_id=mid)
    assert out["governance_task_id"] == gid
    assert out["latest_manifest_id"] == mid
    assert out["current_manifest_id"] is None


def test_resolve_exactly_one_param(resolve_db):
    with pytest.raises(ValueError):
        resolve_governance_task(resolve_db, governance_task_id="a", notion_page_id="b")
    with pytest.raises(ValueError):
        resolve_governance_task(resolve_db)


def test_resolve_missing_returns_none(resolve_db):
    assert resolve_governance_task(resolve_db, governance_task_id="nope") is None
    assert resolve_governance_task(resolve_db, manifest_id="mfst-missing") is None


def test_api_governance_resolve(resolve_db, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_API_TOKEN", "resolve-test-token")
    monkeypatch.setenv("RUN_TELEGRAM", "0")
    fa = _resolve_app()

    def _override():
        yield resolve_db

    fa.dependency_overrides[get_db] = _override
    try:
        np = "api-resolve-z"
        gid = f"gov-notion-{np}"
        create_governance_task(
            resolve_db,
            task_id=gid,
            actor_type="test",
            actor_id="t",
            environment="lab",
        )
        mid, _ = create_manifest(
            resolve_db,
            task_id=gid,
            commands=[{"type": "noop"}],
            scope_summary="x",
            risk_level="low",
            actor_type="test",
            actor_id="t",
            environment="lab",
            attach_and_await_approval=True,
        )
        resolve_db.commit()
        client = TestClient(fa)
        h = {"Authorization": "Bearer resolve-test-token"}

        r400 = client.get("/api/governance/resolve", headers=h)
        assert r400.status_code == 400

        r400b = client.get(
            "/api/governance/resolve",
            params={"task_id": gid, "manifest_id": mid},
            headers=h,
        )
        assert r400b.status_code == 400

        r404 = client.get("/api/governance/resolve", params={"task_id": "missing"}, headers=h)
        assert r404.status_code == 404

        r1 = client.get("/api/governance/resolve", params={"task_id": gid}, headers=h)
        assert r1.status_code == 200
        j = r1.json()
        assert j["governance_task_id"] == gid
        assert j["latest_manifest_id"] == mid
        assert j["current_manifest_id"] == mid

        r2 = client.get("/api/governance/resolve", params={"notion_page_id": np}, headers=h)
        assert r2.status_code == 200
        assert r2.json()["governance_task_id"] == gid

        r3 = client.get("/api/governance/resolve", params={"manifest_id": mid}, headers=h)
        assert r3.status_code == 200
        assert r3.json()["governance_task_id"] == gid
    finally:
        fa.dependency_overrides.pop(get_db, None)
        monkeypatch.delenv("GOVERNANCE_API_TOKEN", raising=False)


def test_timeline_paths_and_urls_manual_task():
    out = timeline_paths_and_urls("gov-manual-only", None)
    assert out["timeline_by_task_path"] == "/api/governance/tasks/gov-manual-only/timeline"
    assert out["timeline_by_notion_path"] is None


def test_timeline_path_quotes_special_chars():
    p = timeline_path_by_governance_task_id("gov-notion-test%2Fweird")
    assert "%" in p or "test" in p


def test_append_governance_telegram_trace_and_agent_note(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://example.com/api")
    lines: list[str] = ["x"]
    append_governance_telegram_trace(
        lines,
        governance_task_id="gov-notion-n1",
        manifest_id="mfst-99",
    )
    assert any("Notion" in ln and "n1" in ln for ln in lines)
    assert any("mfst-99" in ln for ln in lines)
    assert any("/api/governance/tasks/" in ln for ln in lines)

    note = agent_approval_governance_note_lines(
        governance_task_id="gov-notion-n1",
        notion_page_id="n1",
        manifest_id="mfst-99",
    )
    joined = "\n".join(note)
    assert "gov-notion-n1" in joined and "mfst-99" in joined and "Timeline" in joined


def test_send_governance_telegram_summary_includes_trace(monkeypatch):
    monkeypatch.setenv("API_BASE_URL", "https://api.test/api")
    captured: dict[str, str] = {}

    def _fake_send(text: str, **kwargs):
        captured["text"] = text
        return True, 1

    monkeypatch.setattr(
        "app.services.claw_telegram.send_claw_message",
        _fake_send,
    )
    send_governance_telegram_summary(
        "approved",
        task_id="gov-notion-tg-1",
        manifest_id="mfst-zz",
        lines=["By: op"],
    )
    t = captured.get("text", "")
    assert "gov-notion-tg-1" in t
    assert "mfst-zz" in t
    assert "/api/governance/tasks/" in t and "timeline" in t
