"""execute_prepared_notion_task governance gate (bypass + integration smoke)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask
from app.models.trading_settings import TradingSettings
from app.services.governance_agent_bridge import ensure_agent_execute_prepared_manifest
from app.services.governance_service import approve_manifest


@pytest.fixture()
def gate_engine():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GovernanceTask.__table__,
            GovernanceEvent.__table__,
            GovernanceManifest.__table__,
            TradingSettings.__table__,
        ],
    )
    try:
        yield engine
    finally:
        engine.dispose()


@pytest.fixture()
def gate_db(gate_engine):
    Session = sessionmaker(bind=gate_engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


def test_bypass_marker_when_enforce_off(monkeypatch):
    monkeypatch.delenv("ATP_GOVERNANCE_AGENT_ENFORCE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    calls: list[dict] = []

    def _capture(**kw):
        calls.append(kw)

    monkeypatch.setattr(
        "app.services.governance_agent_bridge.log_governance_bypass_legacy_execute_path",
        _capture,
    )
    from app.services.agent_task_executor import _maybe_run_execute_prepared_through_governance

    pt = {
        "task": {"id": "tid-1"},
        "_callback_selection_for_governance": {"selection_reason": "strategy-patch"},
    }
    assert (
        _maybe_run_execute_prepared_through_governance(
            prepared_task=pt,
            executed_at="2020-01-01T00:00:00Z",
            task_id="tid-1",
            task_title="T",
        )
        is None
    )
    assert len(calls) == 1
    assert calls[0].get("path") == "execute_prepared_notion_task"


def test_enforced_without_approval_blocks(monkeypatch, gate_engine, gate_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")

    nid = "blocked-nid"
    pt = {
        "task": {"id": nid},
        "_callback_selection_for_governance": {"selection_reason": "strategy-patch"},
    }
    mid = ensure_agent_execute_prepared_manifest(
        gate_db,
        nid,
        prepared_task=pt,
        callback_selection=pt["_callback_selection_for_governance"],
        title="blocked",
    )
    gate_db.commit()
    assert mid

    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())

    from app.services.agent_task_executor import _maybe_run_execute_prepared_through_governance

    out = _maybe_run_execute_prepared_through_governance(
        prepared_task=pt,
        executed_at="2020-01-01T00:00:00Z",
        task_id=nid,
        task_title="T",
    )
    assert out is not None
    assert out.get("success") is False
    g = out.get("governance") or {}
    assert g.get("blocked") is True


def test_changed_manifest_invalidates_execute(monkeypatch, gate_engine, gate_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "tamper-exec"
    pt = {
        "task": {"id": nid},
        "_callback_selection_for_governance": {"selection_reason": "strategy-patch"},
    }
    cb = pt["_callback_selection_for_governance"]
    mid = ensure_agent_execute_prepared_manifest(
        gate_db, nid, prepared_task=pt, callback_selection=cb, title="t"
    )
    gate_db.commit()
    approve_manifest(gate_db, manifest_id=mid, approved_by="u", environment="lab")
    gate_db.commit()

    mrow = gate_db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid).one()
    cmds = json.loads(mrow.commands_json or "[]")
    cmds.append({"type": "noop"})
    mrow.commands_json = json.dumps(cmds)
    gate_db.commit()

    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())

    from app.services.agent_task_executor import _maybe_run_execute_prepared_through_governance

    out = _maybe_run_execute_prepared_through_governance(
        prepared_task=pt,
        executed_at="2020-01-01T00:00:00Z",
        task_id=nid,
        task_title="T",
    )
    assert out is not None
    assert out.get("success") is False
    summary = (out.get("apply") or {}).get("summary", "")
    assert "digest" in summary.lower() or "invalid" in summary.lower() or "match" in summary.lower()


def test_enforced_classification_conflict_returns_fail_shape(monkeypatch, gate_engine):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    from app.services.agent_execution_policy import (
        ATTR_PROD_MUTATION,
        GOVERNANCE_ACTION_CLASS_KEY,
        GOV_CLASS_PATCH_PREP,
    )

    def _fn(pt):
        return {}

    setattr(_fn, ATTR_PROD_MUTATION, True)
    cb = {
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
        "apply_change_fn": _fn,
        "selection_reason": "test",
    }
    pt = {
        "task": {"id": "conflict-nid"},
        "_callback_selection_for_governance": cb,
    }
    from app.services.agent_task_executor import _maybe_run_execute_prepared_through_governance

    out = _maybe_run_execute_prepared_through_governance(
        prepared_task=pt,
        executed_at="2020-01-01T00:00:00Z",
        task_id="conflict-nid",
        task_title="T",
    )
    assert out is not None
    assert out.get("success") is False
    g = out.get("governance") or {}
    assert g.get("error") == "classification_conflict"
    assert g.get("conflict_type")
    s = Session()
    try:
        assert s.query(GovernanceEvent).count() == 0
    finally:
        s.close()


def test_emit_visibility_error_skips_when_governance_task_row_missing(gate_db):
    from app.services.governance_service import emit_visibility_error_if_governance_task_exists

    assert (
        emit_visibility_error_if_governance_task_exists(
            gate_db,
            governance_task_id="gov-notion-no-such-row",
            phase="test_phase",
            message="blocked",
            signal_hint="blocked",
        )
        is False
    )
    assert gate_db.query(GovernanceEvent).count() == 0


def _payload_hints(sess, gov_task_id: str) -> list[str | None]:
    rows = (
        sess.query(GovernanceEvent)
        .filter(GovernanceEvent.task_id == gov_task_id)
        .order_by(GovernanceEvent.id.asc())
        .all()
    )
    out = []
    for r in rows:
        try:
            p = json.loads(r.payload_json or "{}")
        except json.JSONDecodeError:
            p = {}
        out.append(p.get("signal_hint"))
    return out


def test_classification_conflict_emits_governance_event_when_task_row_exists(monkeypatch, gate_engine, gate_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "conflict-nid-2"
    gov_tid = f"gov-notion-{nid}"
    gate_db.add(GovernanceTask(task_id=gov_tid, source_type="notion", status="requested", risk_level="medium"))
    gate_db.commit()
    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    from app.services.agent_execution_policy import (
        ATTR_PROD_MUTATION,
        GOVERNANCE_ACTION_CLASS_KEY,
        GOV_CLASS_PATCH_PREP,
    )

    def _fn(pt):
        return {}

    setattr(_fn, ATTR_PROD_MUTATION, True)
    cb = {
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
        "apply_change_fn": _fn,
        "selection_reason": "test",
    }
    pt = {"task": {"id": nid}, "_callback_selection_for_governance": cb}
    from app.services.agent_task_executor import _maybe_run_execute_prepared_through_governance

    _maybe_run_execute_prepared_through_governance(
        prepared_task=pt,
        executed_at="2020-01-01T00:00:00Z",
        task_id=nid,
        task_title="T",
    )
    s = Session()
    try:
        hints = _payload_hints(s, gov_tid)
        assert "classification_conflict" in hints
    finally:
        s.close()


def test_blocked_emits_governance_event_when_task_row_exists(monkeypatch, gate_engine, gate_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "blocked-nid-hint"
    gov_tid = f"gov-notion-{nid}"
    gate_db.add(GovernanceTask(task_id=gov_tid, source_type="notion", status="requested", risk_level="medium"))
    gate_db.commit()
    pt = {
        "task": {"id": nid},
        "_callback_selection_for_governance": {"selection_reason": "strategy-patch"},
    }
    mid = ensure_agent_execute_prepared_manifest(
        gate_db,
        nid,
        prepared_task=pt,
        callback_selection=pt["_callback_selection_for_governance"],
        title="blocked",
    )
    gate_db.commit()
    assert mid
    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    from app.services.agent_task_executor import _maybe_run_execute_prepared_through_governance

    _maybe_run_execute_prepared_through_governance(
        prepared_task=pt,
        executed_at="2020-01-01T00:00:00Z",
        task_id=nid,
        task_title="T",
    )
    s = Session()
    try:
        hints = _payload_hints(s, gov_tid)
        assert "blocked" in hints
    finally:
        s.close()


def test_bundle_drift_emits_governance_event_when_task_row_exists(monkeypatch, gate_engine, gate_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "drift-nid"
    gov_tid = f"gov-notion-{nid}"
    gate_db.add(GovernanceTask(task_id=gov_tid, source_type="notion", status="requested", risk_level="medium"))
    gate_db.commit()
    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    from app.services.agent_execution_policy import GOVERNANCE_ACTION_CLASS_KEY, GOV_CLASS_PROD_MUTATION

    def _apply(pt):
        return True

    bundle = {
        "prepared_task": {"task": {"id": nid, "task": "drift"}},
        "callback_selection": {
            "selection_reason": "strategy-patch",
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
            "apply_change_fn": _apply,
        },
        "approval": {"required": False},
        "bundle_fingerprint_approved": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    }
    monkeypatch.setattr(
        "app.services.agent_task_executor._append_notion_page_comment",
        lambda *a, **k: True,
    )
    from app.services.agent_task_executor import execute_prepared_task_if_approved

    out = execute_prepared_task_if_approved(bundle, approved=True)
    assert out.get("execution_skipped") is True
    assert (out.get("governance") or {}).get("error") == "bundle_drift"
    s = Session()
    try:
        hints = _payload_hints(s, gov_tid)
        assert "drift" in hints
    finally:
        s.close()


def test_bundle_drift_no_governance_event_without_task_row(monkeypatch, gate_engine):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "drift-nid-solo"
    gov_tid = f"gov-notion-{nid}"
    Session = sessionmaker(bind=gate_engine, future=True)
    monkeypatch.setattr("app.database.SessionLocal", lambda: Session())
    from app.services.agent_execution_policy import GOVERNANCE_ACTION_CLASS_KEY, GOV_CLASS_PROD_MUTATION

    def _apply(pt):
        return True

    bundle = {
        "prepared_task": {"task": {"id": nid, "task": "drift"}},
        "callback_selection": {
            "selection_reason": "strategy-patch",
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
            "apply_change_fn": _apply,
        },
        "approval": {"required": False},
        "bundle_fingerprint_approved": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    }
    monkeypatch.setattr(
        "app.services.agent_task_executor._append_notion_page_comment",
        lambda *a, **k: True,
    )
    from app.services.agent_task_executor import execute_prepared_task_if_approved

    execute_prepared_task_if_approved(bundle, approved=True)
    s = Session()
    try:
        assert s.query(GovernanceEvent).filter(GovernanceEvent.task_id == gov_tid).count() == 0
    finally:
        s.close()
