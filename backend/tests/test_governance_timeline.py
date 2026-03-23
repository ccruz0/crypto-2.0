"""Governance timeline read model (Phase 1 control-plane)."""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes_governance import router as governance_router
from app.database import Base, get_db
from app.models.agent_approval_state import AgentApprovalState
from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask
from app.services.governance_service import (
    approve_manifest,
    create_governance_task,
    create_manifest,
    emit_finding_event,
)
from app.services.governance_timeline import (
    PAYLOAD_SIGNAL_HINT_KEY,
    TIMELINE_SIGNAL_BLOCKED,
    TIMELINE_SIGNAL_CLASSIFICATION_CONFLICT,
    TIMELINE_SIGNAL_DRIFT,
    TIMELINE_SIGNAL_FAILED,
    build_governance_timeline,
    build_governance_timeline_for_notion,
    derive_timeline_event_signal,
    notion_page_id_from_governance_task_id,
    resolve_timeline_event_signal,
)


@pytest.fixture()
def timeline_db():
    # StaticPool + check_same_thread=False so Starlette TestClient threadpool sees the same DB.
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
            GovernanceEvent.__table__,
            GovernanceManifest.__table__,
            AgentApprovalState.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_notion_page_id_from_governance_task_id():
    assert notion_page_id_from_governance_task_id("gov-notion-abc-123") == "abc-123"
    assert notion_page_id_from_governance_task_id("gov-manual-1") is None


def test_derive_timeline_event_signal_failed_error_type():
    assert (
        derive_timeline_event_signal("error", "failed", {"message": "x"}, "x") == TIMELINE_SIGNAL_FAILED
    )


def test_derive_timeline_event_signal_failed_phase():
    assert derive_timeline_event_signal("action", "failed", {}, "ok") == TIMELINE_SIGNAL_FAILED


def test_derive_timeline_event_signal_classification():
    p = {"reason": "governance_classification_conflict"}
    assert (
        derive_timeline_event_signal("action", "applying", p, "conflict") == TIMELINE_SIGNAL_CLASSIFICATION_CONFLICT
    )


def test_derive_timeline_event_signal_drift_on_error_type_is_failed():
    """error event type always maps to failed before drift substring logic."""
    p = {"error": "governance_bundle_drift_detected"}
    assert derive_timeline_event_signal("error", "validating", p, "drift") == TIMELINE_SIGNAL_FAILED


def test_derive_timeline_event_signal_drift_non_error():
    """Drift wording without error type still tags drift (not failed)."""
    p = {"code": "bundle_drift"}
    assert (
        derive_timeline_event_signal("result", "validating", p, "bundle drift") == TIMELINE_SIGNAL_DRIFT
    )


def test_derive_timeline_event_signal_blocked():
    p = {"message": "governance_execution_blocked"}
    assert derive_timeline_event_signal("action", "planned", p, "blocked") == TIMELINE_SIGNAL_BLOCKED


def test_derive_timeline_event_signal_priority_failed_over_blocked():
    """Failed wins when both match (e.g. error event mentioning blocked)."""
    p = {"message": "failed: execution blocked"}
    assert derive_timeline_event_signal("error", "failed", p, "failed") == TIMELINE_SIGNAL_FAILED


def test_resolve_timeline_event_signal_prefers_explicit_hint():
    """Explicit signal_hint wins even when derivation would differ (e.g. error type → failed)."""
    p = {PAYLOAD_SIGNAL_HINT_KEY: TIMELINE_SIGNAL_DRIFT, "message": "x"}
    assert (
        resolve_timeline_event_signal("error", "failed", p, "error")
        == TIMELINE_SIGNAL_DRIFT
    )


def test_resolve_timeline_event_signal_invalid_hint_falls_back():
    assert (
        resolve_timeline_event_signal(
            "error",
            "failed",
            {PAYLOAD_SIGNAL_HINT_KEY: "not_a_real_signal"},
            "ok",
        )
        == TIMELINE_SIGNAL_FAILED
    )


def test_build_timeline_uses_signal_hint_on_payload(timeline_db):
    tid = "gov-hint-payload-1"
    timeline_db.add(GovernanceTask(task_id=tid, source_type="manual", status="requested", risk_level="low"))
    dt = __import__("datetime").datetime(2025, 7, 1, 12, 0, 0)
    timeline_db.add(
        GovernanceEvent(
            task_id=tid,
            event_id="ev-h1",
            ts=dt,
            type="decision",
            actor_type="human",
            actor_id="u",
            environment="prod",
            payload_json=json.dumps(
                {
                    "decision": "denied",
                    "manifest_id": "mfst-x",
                    PAYLOAD_SIGNAL_HINT_KEY: "blocked",
                }
            ),
        )
    )
    timeline_db.commit()
    out = build_governance_timeline(timeline_db, tid)
    assert out["timeline"][0]["signal"] == "blocked"
    assert out["signal_counts"]["blocked"] == 1
    assert out["signal_counts"]["failed"] == 0


def test_build_timeline_none_when_task_missing(timeline_db):
    assert build_governance_timeline(timeline_db, "missing-task") is None
    assert build_governance_timeline_for_notion(timeline_db, "nonexistent-page") is None


def test_build_timeline_with_manifests_events_and_agent_bundle(timeline_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.governance_service.emit_governance_event",
        lambda *a, **k: "evt-skip",
    )

    notion_pid = "page-uuid-99"
    gid = f"gov-notion-{notion_pid}"
    row = GovernanceTask(
        task_id=gid,
        source_type="notion",
        source_ref=f"https://notion.so/{notion_pid}",
        status="awaiting_approval",
        risk_level="medium",
    )
    timeline_db.add(row)
    timeline_db.flush()

    mid = "mfst-testmanifest01"
    digest = "sha256:" + "a" * 64
    cmds = [
        {
            "type": "agent_execute_prepared_pipeline",
            "audit": {"bundle_fingerprint": "sha256:" + "b" * 64},
        }
    ]
    mf = GovernanceManifest(
        task_id=gid,
        manifest_id=mid,
        digest=digest,
        commands_json=json.dumps(cmds),
        scope_summary="execute prepared",
        risk_level="medium",
        approval_status="approved",
        approved_by="tester",
    )
    timeline_db.add(mf)

    ev1 = GovernanceEvent(
        task_id=gid,
        event_id="evt-001",
        ts=__import__("datetime").datetime(2025, 3, 22, 10, 0, 0),
        type="action",
        actor_type="agent",
        actor_id="openclaw",
        environment="lab",
        payload_json=json.dumps(
            {"name": "manifest_created", "status": "completed", "manifest_id": mid, "digest": digest}
        ),
    )
    ev2 = GovernanceEvent(
        task_id=gid,
        event_id="evt-002",
        ts=__import__("datetime").datetime(2025, 3, 22, 10, 5, 0),
        type="decision",
        actor_type="human",
        actor_id="carlos",
        environment="prod",
        payload_json=json.dumps({"decision": "approved", "manifest_id": mid}),
    )
    timeline_db.add_all([ev1, ev2])

    bundle = {
        "governance_action_class": "prod_mutation",
        "bundle_fingerprint": "sha256:" + "c" * 64,
        "bundle_identity": {"selection_reason": "strategy_patch"},
    }
    timeline_db.add(
        AgentApprovalState(
            task_id=notion_pid,
            status="approved",
            prepared_bundle_json=json.dumps(bundle),
            execution_status="completed",
        )
    )
    timeline_db.commit()

    out = build_governance_timeline(timeline_db, gid)
    assert out is not None
    assert out["correlation_id"] == gid
    assert out["governance_task_id"] == gid
    assert out["notion_page_id"] == notion_pid
    assert out["current_status"] == "awaiting_approval"
    assert out["coverage"]["governance_task_present"] is True
    assert out["coverage"]["notion_linked"] is True
    assert out["coverage"]["agent_bundle_present"] is True
    assert out["coverage"]["timeline_scope"] == "full"
    assert len(out["manifests"]) == 1
    assert out["manifests"][0]["manifest_id"] == mid
    assert out["manifests"][0]["digest"] == digest
    assert out["manifests"][0]["digest_prefix"] == "sha256:aaaaaaaaaaaaaa…"
    assert out["manifests"][0]["bundle_fingerprint_prefix"] == "sha256:bbbbbbbbbbbbbb…"
    assert out["agent_bundle"]["governance_action_class"] == "prod_mutation"
    assert out["agent_bundle"]["bundle_fingerprint_prefix"] == "sha256:cccccccccccccc…"

    assert len(out["timeline"]) == 2
    assert out["signal_counts"] == {
        "failed": 0,
        "drift": 0,
        "classification_conflict": 0,
        "blocked": 0,
    }
    assert out["timeline"][0]["signal"] is None
    dec = out["timeline"][1]
    assert dec["event_type"] == "decision"
    assert dec["signal"] is None
    assert dec["links"]["manifest_id"] == mid
    assert dec["links"]["manifest_digest_prefix"] == "sha256:aaaaaaaaaaaaaa…"

    by_notion = build_governance_timeline_for_notion(timeline_db, notion_pid)
    assert by_notion["governance_task_id"] == gid


def test_build_timeline_partial_without_agent_row(timeline_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.governance_service.emit_governance_event",
        lambda *a, **k: "evt-skip",
    )
    notion_pid = "page-only-gov"
    gid = f"gov-notion-{notion_pid}"
    timeline_db.add(
        GovernanceTask(
            task_id=gid,
            source_type="notion",
            status="requested",
            risk_level="low",
        )
    )
    timeline_db.commit()

    out = build_governance_timeline(timeline_db, gid)
    assert out["coverage"]["agent_bundle_present"] is False
    assert out["coverage"]["timeline_scope"] == "partial"
    assert out["agent_bundle"] is None
    assert out["timeline"] == []
    assert out["signal_counts"] == {
        "failed": 0,
        "drift": 0,
        "classification_conflict": 0,
        "blocked": 0,
    }


def test_build_timeline_signal_counts_per_event(timeline_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.governance_service.emit_governance_event",
        lambda *a, **k: "evt-skip",
    )
    tid = "gov-signal-test-1"
    timeline_db.add(GovernanceTask(task_id=tid, source_type="manual", status="requested", risk_level="low"))
    dt = __import__("datetime").datetime(2025, 6, 1, 12, 0, 0)
    timeline_db.add_all(
        [
            GovernanceEvent(
                task_id=tid,
                event_id="ev-block",
                ts=dt,
                type="action",
                actor_type="system",
                actor_id="s",
                environment="prod",
                payload_json=json.dumps({"message": "governance_execution_blocked"}),
            ),
            GovernanceEvent(
                task_id=tid,
                event_id="ev-err",
                ts=dt,
                type="error",
                actor_type="agent",
                actor_id="a",
                environment="prod",
                payload_json=json.dumps({"message": "step failed"}),
            ),
        ]
    )
    timeline_db.commit()
    out = build_governance_timeline(timeline_db, tid)
    assert out["signal_counts"]["blocked"] == 1
    assert out["signal_counts"]["failed"] == 1
    assert out["signal_counts"]["drift"] == 0
    assert out["signal_counts"]["classification_conflict"] == 0
    assert out["timeline"][0]["signal"] == TIMELINE_SIGNAL_BLOCKED
    assert out["timeline"][1]["signal"] == TIMELINE_SIGNAL_FAILED


def test_governed_only_manual_task_id(timeline_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.governance_service.emit_governance_event",
        lambda *a, **k: "evt-skip",
    )
    tid = "gov-deploy-manual-1"
    timeline_db.add(
        GovernanceTask(task_id=tid, source_type="manual", status="investigating", risk_level="high")
    )
    timeline_db.add(
        GovernanceEvent(
            task_id=tid,
            event_id="e1",
            ts=__import__("datetime").datetime(2025, 1, 1, 12, 0, 0),
            type="finding",
            actor_type="agent",
            actor_id="x",
            environment="lab",
            payload_json=json.dumps({"title": "root cause", "severity": "high"}),
        )
    )
    timeline_db.commit()
    out = build_governance_timeline(timeline_db, tid)
    assert out["notion_page_id"] is None
    assert out["coverage"]["notion_linked"] is False
    assert out["coverage"]["timeline_scope"] == "governed_only"


def _governance_test_app():
    fa = FastAPI()
    fa.include_router(governance_router, prefix="/api")
    return fa


def test_api_timeline_404_and_ok(timeline_db, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_API_TOKEN", "timeline-test-token")
    fa = _governance_test_app()

    def _override_db():
        yield timeline_db

    fa.dependency_overrides[get_db] = _override_db
    try:
        client = TestClient(fa)
        r = client.get(
            "/api/governance/tasks/missing/timeline",
            headers={"Authorization": "Bearer timeline-test-token"},
        )
        assert r.status_code == 404

        tid, _ = create_governance_task(
            timeline_db,
            task_id="gov-api-timeline-1",
            actor_type="test",
            actor_id="t",
            environment="lab",
        )
        emit_finding_event(
            timeline_db,
            task_id=tid,
            actor_type="agent",
            actor_id="a",
            environment="lab",
            title="note",
            severity="low",
        )
        timeline_db.commit()

        r2 = client.get(
            f"/api/governance/tasks/{tid}/timeline",
            headers={"Authorization": "Bearer timeline-test-token"},
        )
        assert r2.status_code == 200
        data = r2.json()
        assert data["governance_task_id"] == tid
        assert data["coverage"]["has_events"] is True
        assert len(data["timeline"]) >= 1
        assert "signal_counts" in data
        assert set(data["signal_counts"].keys()) == {
            "failed",
            "drift",
            "classification_conflict",
            "blocked",
        }
        assert data["timeline"][0].get("signal") in (None, "failed", "drift", "classification_conflict", "blocked")
    finally:
        fa.dependency_overrides.pop(get_db, None)
        monkeypatch.delenv("GOVERNANCE_API_TOKEN", raising=False)


def test_api_by_notion_timeline(timeline_db, monkeypatch):
    monkeypatch.setenv("GOVERNANCE_API_TOKEN", "timeline-test-token-2")
    fa = _governance_test_app()

    def _override_db():
        yield timeline_db

    fa.dependency_overrides[get_db] = _override_db
    try:
        np = "notion-page-xyz"
        gid = f"gov-notion-{np}"
        create_governance_task(
            timeline_db,
            task_id=gid,
            actor_type="test",
            actor_id="t",
            environment="lab",
        )
        timeline_db.commit()

        client = TestClient(fa)
        r = client.get(
            f"/api/governance/by-notion/{np}/timeline",
            headers={"Authorization": "Bearer timeline-test-token-2"},
        )
        assert r.status_code == 200
        assert r.json()["governance_task_id"] == gid

        r404 = client.get(
            "/api/governance/by-notion/unknown-page/timeline",
            headers={"Authorization": "Bearer timeline-test-token-2"},
        )
        assert r404.status_code == 404
    finally:
        fa.dependency_overrides.pop(get_db, None)
        monkeypatch.delenv("GOVERNANCE_API_TOKEN", raising=False)


def test_timeline_with_real_emit_manifest_approve(timeline_db, monkeypatch):
    """Integration-style: real emit events (mirroring may no-op on file)."""
    monkeypatch.setattr(
        "app.services.governance_service.send_telegram",
        lambda *a, **k: None,
        raising=False,
    )
    try:
        monkeypatch.setattr(
            "app.services.governance_service.send_governance_telegram_summary",
            lambda *a, **k: None,
        )
    except Exception:
        pass

    tid, _ = create_governance_task(
        timeline_db,
        task_id="gov-tl-int-1",
        actor_type="test",
        actor_id="t",
        environment="lab",
    )
    mid, man = create_manifest(
        timeline_db,
        task_id=tid,
        commands=[{"type": "noop"}],
        scope_summary="s",
        risk_level="low",
        actor_type="test",
        actor_id="t",
        environment="lab",
        attach_and_await_approval=False,
    )
    approve_manifest(
        timeline_db,
        manifest_id=mid,
        approved_by="op",
        actor_type="human",
        actor_id="op",
        environment="lab",
    )
    timeline_db.commit()

    out = build_governance_timeline(timeline_db, tid)
    assert out["coverage"]["has_manifests"] is True
    assert out["coverage"]["has_events"] is True
    assert any(m["manifest_id"] == mid for m in out["manifests"])
    assert man.digest in [m["digest"] for m in out["manifests"]]
    kinds = {x["event_type"] for x in out["timeline"]}
    assert "action" in kinds
    assert "decision" in kinds
