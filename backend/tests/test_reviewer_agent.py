"""Tests for Jarvis Phase 4 reviewer agent."""

from __future__ import annotations

import pytest

from app.jarvis.agents.patch_agent import create_patch
from app.jarvis.agents.reviewer_agent import review_patch


@pytest.fixture()
def base_patch():
    return create_patch(
        objective="Improve validation checks",
        repository_analysis={"modules": [{"path": "scripts/validate.sh"}]},
        target_files=["scripts/validate.sh"],
    )


def test_review_returns_report(base_patch):
    review = review_patch(patch=base_patch)
    assert review["review_report"]
    assert "# Patch Review Report" in review["review_report"]
    assert review["agent"] == "reviewer_agent"


def test_review_risk_score(base_patch):
    review = review_patch(patch=base_patch)
    assert 0 <= review["risk_score"] <= 100


def test_review_approval_recommendation(base_patch):
    review = review_patch(patch=base_patch)
    assert review["approval_recommendation"] in {"approve_with_review", "needs_approval", "reject"}


def test_review_findings_list(base_patch):
    review = review_patch(patch=base_patch)
    assert isinstance(review["findings"], list)


def test_review_dimensions(base_patch):
    review = review_patch(patch=base_patch)
    expected = {"correctness", "safety", "security", "scope", "policy", "deployment"}
    assert expected.issubset(set(review["dimensions_reviewed"]))


def test_review_policy_compliant(base_patch):
    review = review_patch(patch=base_patch)
    assert review["policy_compliant"] is True


def test_review_no_patch_application(base_patch):
    review = review_patch(patch=base_patch)
    assert review["patch_application_allowed"] is False


def test_review_read_only(base_patch):
    review = review_patch(patch=base_patch)
    assert review["read_only"] is True


def test_review_deployment_finding():
    patch = create_patch(
        objective="Improve validation",
        repository_analysis={"modules": [{"path": "scripts/deploy.sh"}]},
        target_files=["scripts/deploy.sh"],
    )
    review = review_patch(patch=patch)
    deployment_findings = [f for f in review["findings"] if f["dimension"] == "deployment"]
    assert len(deployment_findings) >= 1


def test_review_failed_tests(base_patch):
    review = review_patch(
        patch=base_patch,
        test_results={"ok": False, "failed_count": 3},
    )
    correctness = [f for f in review["findings"] if f["dimension"] == "correctness"]
    assert any("tests failed" in f["finding"] for f in correctness)


def test_review_forbidden_objective():
    patch = create_patch(
        objective="execute trade order now",
        repository_analysis={},
        target_files=["x.py"],
    )
    review = review_patch(patch=patch)
    assert review["policy_compliant"] is False or review["risk_score"] >= 45


def test_review_large_scope():
    patch = create_patch(
        objective="refactor",
        repository_analysis={},
        target_files=[f"f{i}.py" for i in range(8)],
    )
    review = review_patch(patch=patch)
    scope = [f for f in review["findings"] if f["dimension"] == "scope"]
    assert len(scope) >= 1


def test_review_security_sensitive_paths():
    patch = create_patch(
        objective="update env",
        repository_analysis={},
        target_files=[".env", "secrets.json"],
    )
    review = review_patch(patch=patch)
    sec = [f for f in review["findings"] if f["dimension"] == "security"]
    assert len(sec) >= 1


def test_review_markdown_contains_recommendation(base_patch):
    review = review_patch(patch=base_patch)
    assert review["approval_recommendation"] in review["review_report"]


def test_review_created_at(base_patch):
    review = review_patch(patch=base_patch)
    assert review["created_at"]


@pytest.mark.parametrize(
    "risk_score_expectation",
    [
        ("Improve logging", "low"),
        ("deploy production nginx", "high"),
    ],
)
def test_review_risk_levels(risk_score_expectation):
    objective, level = risk_score_expectation
    patch = create_patch(objective=objective, repository_analysis={}, target_files=["a.py"])
    review = review_patch(patch=patch)
    if level == "high":
        assert review["risk_score"] >= 40
    else:
        assert review["risk_score"] < 70


def test_review_empty_diff():
    patch = {"objective": "x", "target_files": [], "unified_diff": "", "risk_assessment": {"risk_score": 10}, "estimated_impact": {"auto_apply": False}}
    review = review_patch(patch=patch)
    assert any("empty" in f["finding"] for f in review["findings"])


def test_review_auto_apply_forbidden():
    patch = {
        "objective": "x",
        "target_files": ["a.py"],
        "unified_diff": "diff",
        "risk_assessment": {"risk_score": 10},
        "estimated_impact": {"auto_apply": True},
    }
    review = review_patch(patch=patch)
    policy = [f for f in review["findings"] if f["dimension"] == "policy"]
    assert any("auto-apply" in f["finding"] for f in policy)


def test_review_with_repository_analysis(base_patch):
    review = review_patch(patch=base_patch, repository_analysis={"modules": []})
    assert review["risk_score"] >= 0
