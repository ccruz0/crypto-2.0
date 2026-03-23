"""Bundle identity fingerprint: stability, drift detection, deserialize behavior."""

from __future__ import annotations

import json

from app.services.agent_bundle_identity import (
    build_bundle_identity_dict,
    compute_bundle_fingerprint,
    verify_bundle_fingerprint,
)
from app.services.agent_execution_policy import GOVERNANCE_ACTION_CLASS_KEY, GOV_CLASS_PATCH_PREP
from app.services.agent_telegram_approval import _deserialize_prepared_bundle, _serialize_prepared_bundle


def test_fingerprint_stable_for_same_identity():
    pt = {"task": {"id": "tid-1", "execution_mode": "normal"}, "execution_mode": "normal"}
    cb = {
        "selection_reason": "documentation task",
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
        "manual_only": False,
    }

    def _apply(x):
        return {}

    cb["apply_change_fn"] = _apply
    i1 = build_bundle_identity_dict(pt, cb)
    i2 = build_bundle_identity_dict(pt, cb)
    assert compute_bundle_fingerprint(i1) == compute_bundle_fingerprint(i2)


def test_changed_governance_class_changes_fingerprint():
    pt = {"task": {"id": "tid-1"}}
    cb1 = {
        "selection_reason": "x",
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
        "apply_change_fn": lambda z: z,
    }
    cb2 = dict(cb1)
    from app.services.agent_execution_policy import GOV_CLASS_PROD_MUTATION

    cb2[GOVERNANCE_ACTION_CLASS_KEY] = GOV_CLASS_PROD_MUTATION
    fp1 = compute_bundle_fingerprint(build_bundle_identity_dict(pt, cb1))
    fp2 = compute_bundle_fingerprint(build_bundle_identity_dict(pt, cb2))
    assert fp1 != fp2


def test_verify_bundle_fingerprint_legacy_missing_expected():
    ok, a, b = verify_bundle_fingerprint(None, {"task": {"id": "1"}}, {})
    assert ok and a is None and b is None


def test_deserialize_preserves_fingerprint_and_skips_refresh_when_fp(monkeypatch):
    calls = []

    def _boom(tid):
        calls.append(tid)
        return None

    monkeypatch.setattr(
        "app.services.notion_task_reader.get_notion_task_by_id",
        _boom,
    )

    pt = {"task": {"id": "abc-def", "type": "bug"}}
    cb = {
        "selection_reason": "bug investigation",
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
        "manual_only": True,
        "apply_change_fn": lambda x: x,
    }
    bundle = {
        "prepared_task": pt,
        "callback_selection": cb,
        "approval": {},
        "approval_summary": "",
    }
    raw = _serialize_prepared_bundle(bundle)
    data = json.loads(raw)
    assert data.get("bundle_fingerprint")
    assert data.get("bundle_identity")

    out = _deserialize_prepared_bundle(raw, execution_load=True)
    assert out
    assert out.get("bundle_fingerprint_approved") == data["bundle_fingerprint"]
    assert calls == []  # Notion refresh skipped when fingerprint present


def test_execute_drift_blocks_when_enforce(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "aws")
    monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")

    from app.services.agent_task_executor import execute_prepared_task_if_approved
    from app.services.agent_bundle_identity import compute_bundle_fingerprint, build_bundle_identity_dict
    from app.services.agent_execution_policy import GOV_CLASS_PROD_MUTATION

    def _apply_a(x):
        return {}

    _apply_a.__module__ = "mod.a"
    _apply_a.__name__ = "fn_a"

    pt = {
        "task": {"id": "n1", "task": "t"},
        "claim": {"status_updated": True},
    }
    cb = {
        "selection_reason": "strategy-patch",
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
        "apply_change_fn": _apply_a,
        "manual_only": False,
    }
    fp = compute_bundle_fingerprint(build_bundle_identity_dict(pt, cb))

    def _apply_b(x):
        return {}

    _apply_b.__module__ = "mod.b"
    _apply_b.__name__ = "fn_b"

    cb2 = dict(cb)
    cb2["apply_change_fn"] = _apply_b

    bundle = {
        "prepared_task": pt,
        "callback_selection": cb2,
        "approval": {"required": False},
        "bundle_fingerprint_approved": fp,
    }
    out = execute_prepared_task_if_approved(bundle, approved=True)
    assert out.get("execution_skipped") is True
    assert (out.get("governance") or {}).get("error") == "bundle_drift"


def test_execute_drift_warns_local(monkeypatch, caplog):
    monkeypatch.setenv("ENVIRONMENT", "local")
    monkeypatch.delenv("ATP_GOVERNANCE_AGENT_ENFORCE", raising=False)

    def _stub_exec(pt, **kwargs):
        tid = str(((pt or {}).get("task") or {}).get("id") or "")
        return {
            "executed_at": "2020-01-01T00:00:00Z",
            "task_id": tid,
            "task_title": "t",
            "apply": {"attempted": True, "success": True, "summary": "stub"},
            "testing": {"status_updated": False},
            "validation": {"attempted": False, "success": False, "summary": ""},
            "deployment": {"attempted": False, "success": False, "summary": ""},
            "final_status": "in-progress",
            "success": True,
        }

    monkeypatch.setattr("app.services.agent_task_executor.execute_prepared_notion_task", _stub_exec)

    from app.services.agent_task_executor import execute_prepared_task_if_approved
    from app.services.agent_bundle_identity import compute_bundle_fingerprint, build_bundle_identity_dict
    from app.services.agent_execution_policy import GOV_CLASS_PATCH_PREP

    def _apply_a(x):
        return {}

    pt = {"task": {"id": "n2", "task": "t"}, "claim": {"status_updated": True}}
    cb = {
        "selection_reason": "documentation",
        GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
        "apply_change_fn": _apply_a,
        "validate_fn": None,
        "deploy_fn": None,
        "manual_only": False,
    }
    fp = compute_bundle_fingerprint(build_bundle_identity_dict(pt, cb))

    def _apply_b(x):
        return {}

    cb2 = dict(cb)
    cb2["apply_change_fn"] = _apply_b

    bundle = {
        "prepared_task": pt,
        "callback_selection": cb2,
        "approval": {"required": False},
        "bundle_fingerprint_approved": fp,
    }
    with caplog.at_level("WARNING"):
        out = execute_prepared_task_if_approved(bundle, approved=True)
    assert out.get("execution_skipped") is not True
    assert "governance_bundle_drift_detected" in caplog.text
