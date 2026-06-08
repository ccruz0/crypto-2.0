"""Tests for Jarvis Decision Intelligence Layer (memory only, no execution)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from app.database import (
    ensure_jarvis_action_plans_table,
    ensure_jarvis_audit_runs_table,
    ensure_jarvis_crypto_audit_runs_table,
    ensure_jarvis_decisions_table,
    ensure_jarvis_executive_reports_table,
)
from app.jarvis.mvp.audit_persistence import record_audit_run
from app.jarvis.mvp.chief_of_staff import generate_executive_report
from app.jarvis.mvp.decision_analytics import (
    apply_decision_adjustments,
    generate_lessons_learned,
    get_decision_analytics,
    get_decision_history_index,
    normalize_recommendation_key,
)
from app.jarvis.mvp.decision_persistence import get_decision, list_decisions, record_decision
from app.jarvis.mvp.decision_service import create_decision
from app.jarvis.mvp.executive_report_persistence import get_executive_report, record_executive_report
from app.jarvis.mvp.executive_report_service import create_executive_report
from app.jarvis.mvp.telegram_executive_report_alerts import format_weekly_executive_report_alert

AWS_AUDIT_OUTPUT = {
    "summary": {"read_only": True},
    "cost_findings": [],
    "security_findings": [
        {
            "severity": "high",
            "category": "security_groups",
            "finding": "1 security group(s) with risky public exposure",
            "count": 1,
        }
    ],
    "resource_findings": [
        {
            "severity": "low",
            "category": "tagging",
            "finding": "5 resource(s) missing required tags",
            "count": 5,
        }
    ],
    "recommendations": [],
    "estimated_monthly_savings": 0.0,
}

MOCK_METRICS = {
    "open_findings": 2,
    "portfolio_difference_pct": 0,
    "read_only": True,
}


@pytest.fixture
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.decision_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.audit_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.crypto_audit_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.action_plan_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.executive_report_persistence.engine", eng)
    assert ensure_jarvis_audit_runs_table(eng)
    assert ensure_jarvis_crypto_audit_runs_table(eng)
    assert ensure_jarvis_action_plans_table(eng)
    assert ensure_jarvis_decisions_table(eng)
    assert ensure_jarvis_executive_reports_table(eng)
    return eng


def test_record_and_list_decisions(sqlite_engine):
    did = record_decision(
        source_type="aws_audit",
        source_id="audit-1",
        decision="approved",
        decision_reason="Restrict open security group ingress",
        outcome="successful",
        reviewed_by="Carlos",
    )
    stored = get_decision(did)
    assert stored is not None
    assert stored["decision"] == "approved"
    assert stored["outcome"] == "successful"
    assert stored["reviewed_by"] == "Carlos"

    decisions = list_decisions(limit=10)
    assert len(decisions) == 1
    assert decisions[0]["decision_id"] == did


def test_create_decision_service(sqlite_engine):
    stored = create_decision(
        source_type="aws_audit",
        source_id="audit-1",
        decision="rejected",
        decision_reason="Apply missing resource tags",
        reviewed_by="Carlos",
    )
    assert stored["decision"] == "rejected"
    assert stored["outcome"] == "unknown"


def test_decision_analytics_counts(sqlite_engine):
    for _ in range(3):
        record_decision(
            decision="rejected",
            decision_reason="Apply missing resource tags",
            reviewed_by="Carlos",
        )
    for _ in range(2):
        record_decision(
            decision="approved",
            decision_reason="Restrict open security group ingress",
            outcome="successful",
            reviewed_by="Carlos",
        )
    record_decision(
        decision="deferred",
        decision_reason="Remove unattached EBS volumes",
        reviewed_by="Carlos",
    )

    analytics = get_decision_analytics()
    assert analytics["rejected_count"] == 3
    assert analytics["approved_count"] == 2
    assert analytics["deferred_count"] == 1
    assert analytics["successful_outcomes"] == 2
    assert analytics["decision_success_rate"] == 100.0
    assert analytics["most_common_rejected_recommendation"] == "Apply missing resource tags"
    assert analytics["most_successful_recommendation_type"] == "Restrict open security group ingress"
    assert analytics["repeated_findings_count"] >= 1


def test_repeated_rejections_lower_priority(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)

    for _ in range(5):
        record_decision(
            decision="rejected",
            decision_reason="Apply missing resource tags",
            reviewed_by="Carlos",
        )

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        report = generate_executive_report()

    titles = [p["title"] for p in report["top_priorities"]]
    tagging_idx = next((i for i, t in enumerate(titles) if "tag" in t.lower()), -1)
    security_idx = next((i for i, t in enumerate(titles) if "security" in t.lower()), -1)
    if tagging_idx >= 0 and security_idx >= 0:
        assert security_idx < tagging_idx


def test_successful_history_boosts_priority(sqlite_engine):
    item = {
        "title": "Restrict open security group ingress",
        "reason": "Risky exposure",
        "priority_score": 40.0,
        "impact": 7,
        "risk": 8,
        "effort": 2,
    }
    history = {
        normalize_recommendation_key("Restrict open security group ingress"): {
            "label": "Restrict open security group ingress",
            "approved": 4,
            "rejected": 0,
            "successful": 4,
            "unsuccessful": 0,
            "total": 4,
        }
    }
    adjusted = apply_decision_adjustments(item, history)
    assert adjusted["priority_score"] > item["priority_score"]
    assert adjusted.get("decision_context")


def test_lessons_learned_generation(sqlite_engine):
    for _ in range(4):
        record_decision(
            decision="approved",
            decision_reason="Restrict open security group ingress",
            outcome="successful",
            reviewed_by="Carlos",
        )
    for _ in range(7):
        record_decision(
            decision="rejected",
            decision_reason="Apply missing resource tags",
            reviewed_by="Carlos",
        )
    record_decision(
        decision="approved",
        decision_reason="Refresh stale portfolio cache",
        outcome="successful",
        reviewed_by="Carlos",
    )
    record_decision(
        decision="approved",
        decision_reason="Refresh stale portfolio cache",
        outcome="successful",
        reviewed_by="Carlos",
    )
    record_decision(
        decision="approved",
        decision_reason="Refresh stale portfolio cache",
        outcome="successful",
        reviewed_by="Carlos",
    )
    record_decision(
        decision="approved",
        decision_reason="Refresh stale portfolio cache",
        outcome="unsuccessful",
        reviewed_by="Carlos",
    )

    lessons = generate_lessons_learned(get_decision_history_index())
    assert any("security group" in lesson.lower() for lesson in lessons)
    assert any("tag" in lesson.lower() or "ignored" in lesson.lower() for lesson in lessons)


def test_executive_report_includes_lessons_learned(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)
    for _ in range(7):
        record_decision(
            decision="rejected",
            decision_reason="Apply missing resource tags",
            reviewed_by="Carlos",
        )

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        with patch(
            "app.jarvis.mvp.executive_report_service.send_weekly_executive_report_alert",
            return_value=False,
        ):
            report = create_executive_report(skip_if_recent=False, send_telegram=False)

    assert report.get("lessons_learned")
    assert len(report["lessons_learned"]) >= 1

    stored = get_executive_report(report["report_id"])
    assert stored is not None
    assert stored.get("lessons_learned")


def test_telegram_includes_lessons_learned():
    report = {
        "overall_health_score": 75,
        "total_potential_savings_usd": 0,
        "top_priorities": [{"priority": 1, "title": "Test", "estimated_savings_usd": 0}],
        "lessons_learned": [
            "Security group remediation has solved 4 similar findings.",
            "Tagging recommendations have been ignored 7 times.",
        ],
    }
    message = format_weekly_executive_report_alert(report)
    assert "Lessons Learned:" in message
    assert "Tagging recommendations have been ignored 7 times." in message
