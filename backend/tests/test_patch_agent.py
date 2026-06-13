"""Tests for Jarvis Phase 4 patch agent."""

from __future__ import annotations

import pytest

from app.jarvis.agents.patch_agent import compare_patch_revisions, create_patch, update_patch
from app.jarvis.execution.safety import SafetyLevel, classify_phase4_action


@pytest.fixture()
def sample_analysis():
    return {
        "modules": [{"path": "backend/app/jarvis/execution/service.py", "line_count": 200}],
        "findings": {"jarvis": [{"path": "backend/app/api/routes_jarvis.py", "line": "1", "text": "router"}]},
    }


@pytest.mark.parametrize(
    "objective",
    [
        "Generate patch to improve deploy validation",
        "Fix websocket handler",
        "Improve OpenClaw guard",
        "Update jarvis routes",
        "Refactor repository agent",
    ],
)
def test_create_patch_returns_diff(objective, sample_analysis):
    patch = create_patch(objective=objective, repository_analysis=sample_analysis)
    assert patch["unified_diff"]
    assert "--- a/" in patch["unified_diff"]
    assert patch["patch_id"]
    assert patch["revision"] == 1
    assert patch["read_only"] is True


def test_create_patch_target_files(sample_analysis):
    patch = create_patch(
        objective="test",
        repository_analysis=sample_analysis,
        target_files=["backend/app/foo.py"],
    )
    assert patch["target_files"] == ["backend/app/foo.py"]


def test_create_patch_risk_assessment(sample_analysis):
    patch = create_patch(objective="deploy validation fix", repository_analysis=sample_analysis)
    risk = patch["risk_assessment"]
    assert "risk_score" in risk
    assert risk["risk_level"] in {"low", "medium", "high"}
    assert isinstance(risk["factors"], list)


def test_create_patch_estimated_impact(sample_analysis):
    patch = create_patch(objective="test change", repository_analysis=sample_analysis)
    impact = patch["estimated_impact"]
    assert impact["requires_approval"] is True
    assert impact["auto_apply"] is False
    assert impact["files_affected"] >= 1


def test_create_patch_safety_level(sample_analysis):
    patch = create_patch(objective="test", repository_analysis=sample_analysis)
    assert patch["safety_level"] == SafetyLevel.SAFE_AUTO.value


def test_update_patch_increments_revision(sample_analysis):
    patch = create_patch(objective="v1", repository_analysis=sample_analysis)
    updated = update_patch(patch, notes="refined approach")
    assert updated["revision"] == 2
    assert updated["previous_revision"] == 1
    assert "refined approach" in updated["unified_diff"]


def test_update_patch_objective_override(sample_analysis):
    patch = create_patch(objective="old", repository_analysis=sample_analysis)
    updated = update_patch(patch, objective="new objective")
    assert updated["objective"] == "new objective"


def test_compare_patch_revisions(sample_analysis):
    left = create_patch(objective="a", repository_analysis=sample_analysis)
    right = update_patch(left, notes="delta")
    cmp = compare_patch_revisions(left, right)
    assert cmp["left_revision"] == 1
    assert cmp["right_revision"] == 2


def test_compare_same_revision(sample_analysis):
    patch = create_patch(objective="same", repository_analysis=sample_analysis)
    cmp = compare_patch_revisions(patch, patch)
    assert cmp["lines_only_in_left"] == 0
    assert cmp["lines_only_in_right"] == 0


def test_patch_content_hash_changes(sample_analysis):
    left = create_patch(objective="a", repository_analysis=sample_analysis)
    right = update_patch(left, notes="change")
    assert left["content_hash"] != right["content_hash"]


@pytest.mark.parametrize(
    "action,expected",
    [
        ("patch_generation", SafetyLevel.SAFE_AUTO),
        ("patch_application", SafetyLevel.NEEDS_APPROVAL),
        ("pr_creation", SafetyLevel.NEEDS_APPROVAL),
        ("merge", SafetyLevel.FORBIDDEN),
        ("deploy", SafetyLevel.FORBIDDEN),
        ("trading", SafetyLevel.FORBIDDEN),
        ("secrets_access", SafetyLevel.FORBIDDEN),
    ],
)
def test_phase4_action_classification(action, expected):
    assert classify_phase4_action(action) == expected


def test_infer_target_files_from_objective(sample_analysis):
    patch = create_patch(objective="analyze routes_jarvis.py endpoints", repository_analysis=sample_analysis)
    assert len(patch["target_files"]) >= 1


def test_patch_summary_present(sample_analysis):
    patch = create_patch(objective="summary test", repository_analysis=sample_analysis)
    assert "summary test" in patch["patch_summary"].lower() or "Proposed" in patch["patch_summary"]


def test_multiple_target_files_in_diff(sample_analysis):
    patch = create_patch(
        objective="multi",
        repository_analysis=sample_analysis,
        target_files=["a.py", "b.py", "c.py"],
    )
    assert patch["unified_diff"].count("--- a/") == 3


def test_patch_no_auto_apply_flag(sample_analysis):
    patch = create_patch(objective="safe change", repository_analysis=sample_analysis)
    assert patch["estimated_impact"]["auto_apply"] is False


def test_risk_score_bounded(sample_analysis):
    patch = create_patch(objective="deploy production nginx", repository_analysis=sample_analysis)
    assert 0 <= patch["risk_assessment"]["risk_score"] <= 100


def test_created_at_timestamp(sample_analysis):
    patch = create_patch(objective="ts", repository_analysis=sample_analysis)
    assert patch["created_at"]


def test_update_preserves_patch_id(sample_analysis):
    patch = create_patch(objective="id", repository_analysis=sample_analysis)
    updated = update_patch(patch, notes="x")
    assert updated["patch_id"] == patch["patch_id"]


def test_compare_risk_delta(sample_analysis):
    left = create_patch(objective="low risk", repository_analysis=sample_analysis)
    right = update_patch(left, objective="deploy production nginx everywhere", notes="big")
    cmp = compare_patch_revisions(left, right)
    assert "risk_delta" in cmp
