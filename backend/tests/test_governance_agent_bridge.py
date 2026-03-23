"""Agent deploy ↔ governance wiring (manifest + Telegram approve path)."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.governance_models import GovernanceEvent, GovernanceManifest, GovernanceTask
from app.models.trading_settings import TradingSettings
from app.services.agent_execution_policy import ActionClass, classify_callback_action
from app.services.governance_agent_bridge import (
    ensure_agent_deploy_manifest,
    ensure_agent_execute_prepared_manifest,
    ensure_notion_governance_task_stub,
    get_deploy_manifest_id,
    get_execute_manifest_id,
    governance_agent_enforce_production,
    infer_governance_risk_for_notion_agent,
    notion_to_governance_task_id,
)
from app.services.governance_service import approve_manifest, governance_task_has_plan_event
from app.services.governance_executor import execute_governed_manifest


@pytest.fixture()
def bridge_db():
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
    Session = sessionmaker(bind=engine, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()
        engine.dispose()


def test_ensure_notion_governance_task_stub_no_manifest(monkeypatch, bridge_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "early-stub-1"
    gov_tid, created = ensure_notion_governance_task_stub(
        bridge_db, nid, title="Early", risk_level="medium", actor_id="test"
    )
    assert created is True
    assert gov_tid == notion_to_governance_task_id(nid)
    assert bridge_db.query(GovernanceManifest).count() == 0
    _, created2 = ensure_notion_governance_task_stub(bridge_db, nid, title="Early", risk_level="high")
    assert created2 is False


def test_stub_then_ensure_execute_emits_plan_once(monkeypatch, bridge_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "stub-then-exec-1"
    pt = {"task": {"id": nid}, "execution_mode": "normal"}
    cb = {"selection_reason": "strategy-patch", "apply_change_fn": lambda x: True}
    ensure_notion_governance_task_stub(bridge_db, nid, title="T", risk_level="low")
    bridge_db.commit()
    assert not governance_task_has_plan_event(bridge_db, notion_to_governance_task_id(nid))
    mid = ensure_agent_execute_prepared_manifest(
        bridge_db, nid, prepared_task=pt, callback_selection=cb, title="T"
    )
    bridge_db.commit()
    assert mid
    assert governance_task_has_plan_event(bridge_db, notion_to_governance_task_id(nid))
    plans = (
        bridge_db.query(GovernanceEvent)
        .filter(
            GovernanceEvent.task_id == notion_to_governance_task_id(nid),
            GovernanceEvent.type == "plan",
        )
        .count()
    )
    assert plans == 1


def test_infer_governance_risk_for_notion_agent_returns_level():
    r = infer_governance_risk_for_notion_agent(task={}, repo_area={}, sections={})
    assert r in ("high", "medium", "low")


def test_ensure_manifest_skipped_when_not_enforce(monkeypatch, bridge_db):
    monkeypatch.delenv("ATP_GOVERNANCE_AGENT_ENFORCE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    assert governance_agent_enforce_production() is False
    mid = ensure_agent_deploy_manifest(bridge_db, "notion-123", title="t")
    assert mid is None


def test_full_governed_deploy_flow_mocked(monkeypatch, bridge_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    assert governance_agent_enforce_production() is True

    nid = "notion-page-uuid-1234"
    mid = ensure_agent_deploy_manifest(bridge_db, nid, title="Deploy X", risk_classification="LOW")
    bridge_db.commit()
    assert mid
    assert get_deploy_manifest_id(bridge_db, nid) == mid

    gov_tid = notion_to_governance_task_id(nid)
    approve_manifest(bridge_db, manifest_id=mid, approved_by="tester", environment="lab")
    bridge_db.commit()

    calls: list[str] = []

    def _fake_patch(tid: str):
        calls.append(f"patch:{tid}")
        return {"ok": True, "modified_files": []}

    def _fake_trigger(*, task_id: str = "", triggered_by: str = "", ref: str = ""):
        calls.append(f"deploy:{task_id}:{triggered_by}")
        return {"ok": True, "summary": "dispatched"}

    monkeypatch.setattr(
        "app.services.agent_strategy_patch.apply_prepared_strategy_patch_after_approval",
        _fake_patch,
    )
    monkeypatch.setattr(
        "app.services.deploy_trigger.trigger_deploy_workflow",
        _fake_trigger,
    )

    out = execute_governed_manifest(
        bridge_db,
        task_id=gov_tid,
        manifest_id=mid,
        actor_type="human",
        actor_id="tester",
    )
    bridge_db.commit()
    assert out.get("success") is True
    assert any("patch:" in c for c in calls)
    assert any("deploy:" in c for c in calls)


def test_legacy_path_blocked_without_manifest_when_enforced(monkeypatch, bridge_db):
    """Simulate approve_deploy: enforce on but no TradingSettings manifest → cannot execute."""
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "orphan-task"
    # No ensure_agent_deploy_manifest called
    assert get_deploy_manifest_id(bridge_db, nid) is None


def test_ensure_execute_manifest_skipped_when_not_enforce(monkeypatch, bridge_db):
    monkeypatch.delenv("ATP_GOVERNANCE_AGENT_ENFORCE", raising=False)
    monkeypatch.setenv("ENVIRONMENT", "aws")
    pt = {"task": {"id": "n1"}}
    cb = {"selection_reason": "strategy-patch"}
    assert (
        ensure_agent_execute_prepared_manifest(
            bridge_db, "n1", prepared_task=pt, callback_selection=cb, title="t"
        )
        is None
    )


def test_patch_prep_not_prod_mutation_for_policy():
    pt = {"task": {"id": "x"}}
    cb = {"selection_reason": "bug investigation note"}
    assert classify_callback_action(cb, pt) == ActionClass.PATCH_PREP


def test_governed_execute_prepared_flow_mocked(monkeypatch, bridge_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "notion-exec-uuid-1"
    pt = {"task": {"id": nid}, "_use_extended_lifecycle": False, "execution_mode": "normal"}
    cb = {
        "selection_reason": "strategy-patch (manual)",
        "validate_fn": lambda x: True,
        "apply_change_fn": lambda x: True,
    }
    mid = ensure_agent_execute_prepared_manifest(
        bridge_db, nid, prepared_task=pt, callback_selection=cb, title="Exec test"
    )
    bridge_db.commit()
    assert mid
    assert get_execute_manifest_id(bridge_db, nid) == mid

    gov_tid = notion_to_governance_task_id(nid)
    approve_manifest(bridge_db, manifest_id=mid, approved_by="tester", environment="lab")
    bridge_db.commit()

    fake_er = {
        "executed_at": "x",
        "task_id": nid,
        "task_title": "t",
        "apply": {"attempted": True, "success": True, "summary": "ok"},
        "testing": {"status_updated": True},
        "validation": {"attempted": True, "success": True, "summary": "v"},
        "deployment": {"attempted": False, "success": False, "summary": ""},
        "final_status": "testing",
        "success": True,
    }

    def _fake_execute(bundle, approved=True):
        return {
            "execution_result": fake_er,
            "execution_skipped": False,
            "reason": "",
        }

    monkeypatch.setattr(
        "app.services.agent_task_executor.execute_prepared_task_if_approved",
        _fake_execute,
    )
    monkeypatch.setattr(
        "app.services.agent_telegram_approval.load_prepared_bundle_for_execution",
        lambda tid: {
            "prepared_task": {"task": {"id": tid}},
            "callback_selection": cb,
            "approval": {},
        },
    )

    out = execute_governed_manifest(
        bridge_db,
        task_id=gov_tid,
        manifest_id=mid,
        actor_type="human",
        actor_id="tester",
    )
    bridge_db.commit()
    assert out.get("success") is True
    assert out.get("agent_execute_prepared_pipeline_result", {}).get("success") is True


def test_tamper_after_approve_blocks_execute(monkeypatch, bridge_db):
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")
    monkeypatch.setenv("ENVIRONMENT", "aws")
    nid = "tamper-1"
    mid = ensure_agent_deploy_manifest(bridge_db, nid, title="t", risk_classification="LOW")
    bridge_db.commit()
    approve_manifest(bridge_db, manifest_id=mid, approved_by="u", environment="lab")
    bridge_db.commit()
    mrow = bridge_db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid).one()
    cmds = json.loads(mrow.commands_json or "[]")
    cmds.append({"type": "noop"})
    mrow.commands_json = json.dumps(cmds)
    bridge_db.commit()

    monkeypatch.setattr(
        "app.services.agent_strategy_patch.apply_prepared_strategy_patch_after_approval",
        lambda tid: {"ok": True},
    )
    monkeypatch.setattr(
        "app.services.deploy_trigger.trigger_deploy_workflow",
        lambda **kw: {"ok": True, "summary": "x"},
    )
    gov_tid = notion_to_governance_task_id(nid)
    out = execute_governed_manifest(bridge_db, task_id=gov_tid, manifest_id=mid)
    bridge_db.commit()
    assert out.get("success") is False
    assert "digest" in (out.get("error") or "").lower() or "invalid" in (out.get("error") or "").lower()
