"""
Tests for agent execution policy (classification, governance safety).

On AWS, unknown apply callables must fail closed to prod_mutation.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from app.services.agent_execution_policy import (
    GOVERNANCE_ACTION_CLASS_KEY,
    GOV_CLASS_PATCH_PREP,
    GOV_CLASS_PROD_MUTATION,
    ActionClass,
    ATTR_PROD_MUTATION,
    ATTR_SAFE_LAB_APPLY,
    GovernanceClassificationConflictError,
    classify_callback_action,
    get_policy_summary,
    is_safe_autonomous_mode,
    requires_approval_before_apply,
    validate_governance_classification_inputs,
)


class TestClassifyCallbackAction:
    def test_explicit_patch_prep_overrides_aws(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        sel = {
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP,
            "selection_reason": "anything",
            "apply_change_fn": lambda x: x,
        }
        assert classify_callback_action(sel, {}) == ActionClass.PATCH_PREP

    def test_explicit_prod_mutation(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        sel = {
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
            "selection_reason": "x",
            "apply_change_fn": lambda x: x,
        }
        assert classify_callback_action(sel, {}) == ActionClass.PROD_MUTATION

    def test_aws_unknown_apply_defaults_prod_mutation_with_warning(self, monkeypatch, caplog):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")

        def _unknown(pt):
            return {"success": True}

        sel = {"selection_reason": "totally custom operator callback", "apply_change_fn": _unknown}
        with caplog.at_level("WARNING"):
            out = classify_callback_action(sel, {}, log_context="test")
        assert out == ActionClass.PROD_MUTATION
        assert "classification_uncertain_defaulted_to_prod_mutation" in caplog.text

    def test_aws_strategy_patch_callable_prod_marker(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        from app.services.agent_strategy_patch import apply_strategy_patch_task

        sel = {"selection_reason": "strategy-patch task", "apply_change_fn": apply_strategy_patch_task}
        assert classify_callback_action(sel, {}) == ActionClass.PROD_MUTATION

    def test_aws_openclaw_apply_has_safe_marker(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        from app.services.agent_callbacks import select_default_callbacks_for_task

        pt = {
            "task": {
                "id": "00000000-0000-0000-0000-000000000001",
                "type": "bug",
                "task": "Investigate timeout",
                "details": "x",
            }
        }
        cb = select_default_callbacks_for_task(pt)
        assert cb.get("apply_change_fn")
        assert getattr(cb["apply_change_fn"], ATTR_SAFE_LAB_APPLY, False) is True
        assert classify_callback_action(cb, pt) == ActionClass.PATCH_PREP

    def test_local_bug_investigation_reason_without_explicit_class(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "local")
        sel = {"selection_reason": "bug investigation OpenClaw"}
        assert classify_callback_action(sel, {}) == ActionClass.PATCH_PREP

    def test_local_documentation_patch_prep(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "local")
        sel = {"selection_reason": "documentation"}
        assert classify_callback_action(sel, {}) == ActionClass.PATCH_PREP

    def test_local_unknown_reason_defaults_prod(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "local")
        sel = {"selection_reason": "unknown-custom-callback"}
        assert classify_callback_action(sel, {}) == ActionClass.PROD_MUTATION

    def test_empty_selection_defaults_to_prod_mutation(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "local")
        assert classify_callback_action({}) == ActionClass.PROD_MUTATION
        assert classify_callback_action(None) == ActionClass.PROD_MUTATION

    def test_safe_module_allowlist_documentation_callback(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        from app.services.agent_callbacks import apply_documentation_task

        sel = {"selection_reason": "orphan", "apply_change_fn": apply_documentation_task}
        assert classify_callback_action(sel, {}) == ActionClass.PATCH_PREP

    def test_conflicting_explicit_patch_prep_and_prod_marker_aws_enforce_raises(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")

        def _fn(pt):
            return {}

        setattr(_fn, ATTR_PROD_MUTATION, True)
        sel = {GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP, "apply_change_fn": _fn, "selection_reason": "x"}
        with pytest.raises(GovernanceClassificationConflictError) as ei:
            classify_callback_action(sel, {}, log_context="test")
        assert "explicit_patch_prep" in (ei.value.conflict_type or "")

    def test_conflicting_explicit_prod_mutation_and_safe_marker_aws_enforce_raises(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")

        def _fn(pt):
            return {}

        setattr(_fn, ATTR_SAFE_LAB_APPLY, True)
        sel = {GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION, "apply_change_fn": _fn}
        with pytest.raises(GovernanceClassificationConflictError) as ei:
            classify_callback_action(sel, {})
        assert "explicit_prod_mutation" in (ei.value.conflict_type or "")

    def test_metadata_conflict_local_warns_and_fail_safe_prod_mutation(self, monkeypatch, caplog):
        monkeypatch.setenv("ENVIRONMENT", "local")

        def _fn(pt):
            return {}

        setattr(_fn, ATTR_PROD_MUTATION, True)
        sel = {GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PATCH_PREP, "apply_change_fn": _fn}
        with caplog.at_level("WARNING"):
            out = classify_callback_action(sel, {}, log_context="lab")
        assert out == ActionClass.PROD_MUTATION
        assert "governance_classification_conflict" in caplog.text

    def test_dual_markers_conflict_aws_enforce_raises(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        monkeypatch.setenv("ATP_GOVERNANCE_AGENT_ENFORCE", "true")

        def _fn(pt):
            return {}

        setattr(_fn, ATTR_PROD_MUTATION, True)
        setattr(_fn, ATTR_SAFE_LAB_APPLY, True)
        sel = {"apply_change_fn": _fn, "selection_reason": "x"}
        with pytest.raises(GovernanceClassificationConflictError) as ei:
            classify_callback_action(sel, {})
        assert ei.value.conflict_type == "dual_safe_lab_and_prod_mutation_markers"

    def test_validate_inputs_detects_explicit_vs_allowlist(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "aws")
        from app.services.agent_callbacks import apply_documentation_task

        sel = {
            GOVERNANCE_ACTION_CLASS_KEY: GOV_CLASS_PROD_MUTATION,
            "apply_change_fn": apply_documentation_task,
        }
        v = validate_governance_classification_inputs(sel)
        assert v.is_conflicting
        assert v.conflict_type == "explicit_prod_mutation_vs_structural_safe"


class TestRequiresApprovalBeforeApply:
    def test_prod_mutation_requires_approval(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "local")
        sel = {"selection_reason": "strategy-patch"}
        assert requires_approval_before_apply(sel) is True

    def test_patch_prep_no_approval(self, monkeypatch):
        monkeypatch.setenv("ENVIRONMENT", "local")
        sel = {"selection_reason": "bug investigation"}
        assert requires_approval_before_apply(sel) is False


class TestIsSafeAutonomousMode:
    def test_default_true(self):
        with patch.dict("os.environ", {"ATP_SAFE_AUTONOMOUS_MODE": ""}):
            assert is_safe_autonomous_mode() is True

    def test_explicit_true(self):
        with patch.dict("os.environ", {"ATP_SAFE_AUTONOMOUS_MODE": "true"}):
            assert is_safe_autonomous_mode() is True
        with patch.dict("os.environ", {"ATP_SAFE_AUTONOMOUS_MODE": "1"}):
            assert is_safe_autonomous_mode() is True
        with patch.dict("os.environ", {"ATP_SAFE_AUTONOMOUS_MODE": "yes"}):
            assert is_safe_autonomous_mode() is True

    def test_explicit_false(self):
        with patch.dict("os.environ", {"ATP_SAFE_AUTONOMOUS_MODE": "false"}):
            assert is_safe_autonomous_mode() is False
        with patch.dict("os.environ", {"ATP_SAFE_AUTONOMOUS_MODE": "0"}):
            assert is_safe_autonomous_mode() is False


class TestGetPolicySummary:
    def test_returns_dict(self):
        s = get_policy_summary()
        assert isinstance(s, dict)
        assert "safe_autonomous_mode" in s
        assert "prod_mutation_requires_approval" in s
        assert s["prod_mutation_requires_approval"] is True
        assert s.get("governance_action_class_key") == GOVERNANCE_ACTION_CLASS_KEY


def test_classification_audit_report_sample_runs():
    script = Path(__file__).resolve().parents[1] / "scripts" / "classification_audit_report.py"
    r = subprocess.run(
        [sys.executable, str(script), "--sample"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert r.returncode == 0
    assert "Total parsed records" in r.stdout
    assert "governance_classification_conflict" in r.stdout
