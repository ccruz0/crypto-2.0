"""Governance: digest, lifecycle, manifest approval, executor gate."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask
from app.services.governance_executor import execute_governed_manifest
from app.services.governance_service import (
    APPROVAL_STATUS_INVALIDATED,
    ST_COMPLETED,
    ST_INVESTIGATING,
    ST_PATCH_READY,
    approve_manifest,
    compute_manifest_digest,
    create_governance_task,
    create_manifest,
    is_manifest_approved_and_valid,
    transition_task_state,
)


@pytest.fixture()
def gov_db():
    engine = create_engine("sqlite:///:memory:", future=True)
    Base.metadata.create_all(
        bind=engine,
        tables=[
            GovernanceTask.__table__,
            GovernanceEvent.__table__,
            GovernanceManifest.__table__,
        ],
    )
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_compute_manifest_digest_stable_and_sensitive():
    cmds = [{"type": "noop", "x": 1}]
    d1 = compute_manifest_digest(cmds, "scope a", "low")
    d2 = compute_manifest_digest(cmds, "scope a", "low")
    assert d1 == d2
    assert d1.startswith("sha256:")
    d3 = compute_manifest_digest(cmds, "scope b", "low")
    assert d3 != d1


def test_transition_allowed_and_blocked(gov_db):
    tid, _ = create_governance_task(
        gov_db,
        task_id="gov-test-1",
        actor_type="test",
        actor_id="t",
        environment="lab",
    )
    gov_db.commit()
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_INVESTIGATING,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_PATCH_READY,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    gov_db.commit()
    row = gov_db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).one()
    assert row.status == ST_PATCH_READY

    with pytest.raises(ValueError, match="transition not allowed"):
        transition_task_state(
            gov_db,
            task_id=tid,
            to_state=ST_COMPLETED,
            actor_type="test",
            actor_id="t",
            environment="lab",
            send_telegram=False,
        )


def test_execute_denied_without_approval(gov_db, monkeypatch):
    monkeypatch.delenv("ATP_GOVERNANCE_ENFORCE", raising=False)
    tid, _ = create_governance_task(gov_db, task_id="gov-ex-1", actor_type="test", actor_id="t", environment="lab")
    gov_db.commit()
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_INVESTIGATING,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_PATCH_READY,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    gov_db.commit()
    mid, _ = create_manifest(
        gov_db,
        task_id=tid,
        commands=[{"type": "noop"}],
        scope_summary="test",
        risk_level="low",
        attach_and_await_approval=True,
        environment="lab",
    )
    gov_db.commit()

    out = execute_governed_manifest(gov_db, task_id=tid, manifest_id=mid)
    gov_db.commit()
    assert out["success"] is False
    assert "not approved" in (out.get("error") or "").lower()


def test_execute_approved_noop(gov_db, monkeypatch):
    monkeypatch.delenv("ATP_GOVERNANCE_ENFORCE", raising=False)
    tid, _ = create_governance_task(gov_db, task_id="gov-ex-2", actor_type="test", actor_id="t", environment="lab")
    gov_db.commit()
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_INVESTIGATING,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_PATCH_READY,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    gov_db.commit()
    mid, _ = create_manifest(
        gov_db,
        task_id=tid,
        commands=[{"type": "noop", "message": "ok"}],
        scope_summary="noop",
        risk_level="low",
        attach_and_await_approval=True,
        environment="lab",
    )
    gov_db.commit()
    approve_manifest(gov_db, manifest_id=mid, approved_by="tester", actor_type="human", actor_id="tester", environment="lab")
    gov_db.commit()

    out = execute_governed_manifest(gov_db, task_id=tid, manifest_id=mid)
    gov_db.commit()
    assert out["success"] is True
    task = gov_db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).one()
    assert task.status == ST_COMPLETED


def test_tamper_commands_invalidates(gov_db, monkeypatch):
    monkeypatch.delenv("ATP_GOVERNANCE_ENFORCE", raising=False)
    tid, _ = create_governance_task(gov_db, task_id="gov-tamper", actor_type="test", actor_id="t", environment="lab")
    gov_db.commit()
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_INVESTIGATING,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    transition_task_state(
        gov_db,
        task_id=tid,
        to_state=ST_PATCH_READY,
        actor_type="test",
        actor_id="t",
        environment="lab",
        send_telegram=False,
    )
    gov_db.commit()
    mid, mrow = create_manifest(
        gov_db,
        task_id=tid,
        commands=[{"type": "noop"}],
        scope_summary="s",
        risk_level="low",
        attach_and_await_approval=True,
        environment="lab",
    )
    gov_db.commit()
    approve_manifest(gov_db, manifest_id=mid, approved_by="tester", environment="lab")
    gov_db.commit()

    mrow.commands_json = json.dumps([{"type": "docker_compose_restart"}])
    gov_db.commit()

    ok, reason = is_manifest_approved_and_valid(gov_db, mid, expected_commands=json.loads(mrow.commands_json))
    assert ok is False
    gov_db.refresh(mrow)
    assert mrow.approval_status == APPROVAL_STATUS_INVALIDATED


def test_backend_restart_blocked_when_enforce_on_aws(monkeypatch):
    monkeypatch.setenv("ATP_GOVERNANCE_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    from fastapi import HTTPException

    from app.services.governance_enforcement import raise_if_backend_restart_blocked

    with pytest.raises(HTTPException) as ei:
        raise_if_backend_restart_blocked()
    assert ei.value.status_code == 403


def test_backend_restart_allowed_when_enforce_off(monkeypatch):
    monkeypatch.delenv("ATP_GOVERNANCE_ENFORCE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    from app.services.governance_enforcement import raise_if_backend_restart_blocked

    raise_if_backend_restart_blocked()  # no-op
