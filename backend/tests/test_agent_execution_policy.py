"""
Tests for agent execution policy (safe autonomous mode).

Validates:
- Action classification (read_only, safe_ops, patch_prep, prod_mutation)
- requires_approval_before_apply for prod_mutation
- is_safe_autonomous_mode env var behavior
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.services.agent_execution_policy import (
    ActionClass,
    classify_callback_action,
    get_policy_summary,
    is_safe_autonomous_mode,
    requires_approval_before_apply,
)


class TestClassifyCallbackAction:
    """Classify callback by selection_reason."""

    def test_strategy_patch_is_prod_mutation(self):
        sel = {"selection_reason": "strategy-patch for signal tuning"}
        assert classify_callback_action(sel) == ActionClass.PROD_MUTATION

    def test_profile_setting_analysis_is_prod_mutation(self):
        sel = {"selection_reason": "profile-setting-analysis"}
        assert classify_callback_action(sel) == ActionClass.PROD_MUTATION

    def test_bug_investigation_is_patch_prep(self):
        sel = {"selection_reason": "bug investigation OpenClaw"}
        assert classify_callback_action(sel) == ActionClass.PATCH_PREP

    def test_documentation_is_patch_prep(self):
        sel = {"selection_reason": "documentation"}
        assert classify_callback_action(sel) == ActionClass.PATCH_PREP

    def test_monitoring_is_patch_prep(self):
        sel = {"selection_reason": "monitoring triage"}
        assert classify_callback_action(sel) == ActionClass.PATCH_PREP

    def test_strategy_analysis_is_patch_prep(self):
        sel = {"selection_reason": "strategy-analysis"}
        assert classify_callback_action(sel) == ActionClass.PATCH_PREP

    def test_unknown_defaults_to_prod_mutation(self):
        sel = {"selection_reason": "unknown-custom-callback"}
        assert classify_callback_action(sel) == ActionClass.PROD_MUTATION

    def test_empty_selection_defaults_to_prod_mutation(self):
        assert classify_callback_action({}) == ActionClass.PROD_MUTATION
        assert classify_callback_action(None) == ActionClass.PROD_MUTATION


class TestRequiresApprovalBeforeApply:
    """Approval required only for prod_mutation."""

    def test_prod_mutation_requires_approval(self):
        sel = {"selection_reason": "strategy-patch"}
        assert requires_approval_before_apply(sel) is True

    def test_patch_prep_no_approval(self):
        sel = {"selection_reason": "bug investigation"}
        assert requires_approval_before_apply(sel) is False


class TestIsSafeAutonomousMode:
    """ATP_SAFE_AUTONOMOUS_MODE env behavior."""

    def test_default_true(self):
        # When unset or empty, defaults to True
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
    """Policy summary for logging."""

    def test_returns_dict(self):
        s = get_policy_summary()
        assert isinstance(s, dict)
        assert "safe_autonomous_mode" in s
        assert "prod_mutation_requires_approval" in s
        assert s["prod_mutation_requires_approval"] is True
