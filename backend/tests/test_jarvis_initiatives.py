"""Tests for Jarvis Operating System layer (initiatives)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

from app.database import ensure_jarvis_executive_reports_table, ensure_jarvis_initiatives_table
from app.jarvis.mvp.chief_of_staff import generate_executive_report
from app.jarvis.mvp.decision_analytics import apply_initiative_confidence_adjustments, get_initiative_outcome_index
from app.jarvis.mvp.executive_report_persistence import get_executive_report, record_executive_report
from app.jarvis.mvp.initiative_persistence import (
    calculate_initiative_health,
    get_execution_review,
    is_initiative_overdue,
    list_initiatives,
    record_initiative,
    update_initiative,
)
from app.jarvis.mvp.initiative_service import create_initiative, seed_sample_initiatives, update_initiative_record
from app.jarvis.mvp.metrics_persistence import get_executive_dashboard

AWS_AUDIT_OUTPUT = {
    "summary": {"read_only": True},
    "cost_findings": [],
    "security_findings": [],
    "resource_findings": [],
    "recommendations": [],
    "estimated_monthly_savings": 0.0,
}

MOCK_METRICS = {
    "metric_date": "2026-06-08",
    "open_findings": 0,
    "critical_findings": 0,
    "portfolio_difference_pct": 0.0,
    "read_only": True,
}


@pytest.fixture
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.initiative_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.executive_report_persistence.engine", eng)
    assert ensure_jarvis_initiatives_table(eng)
    assert ensure_jarvis_executive_reports_table(eng)
    return eng


def test_health_rules(sqlite_engine):
    today = datetime.now(timezone.utc).date()
    overdue_date = (today - timedelta(days=5)).isoformat()

    assert calculate_initiative_health({"status": "blocked", "updated_at": datetime.now(timezone.utc).isoformat()}) == "red"
    assert (
        calculate_initiative_health(
            {
                "status": "active",
                "target_date": overdue_date,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        == "red"
    )
    stale_date = (datetime.now(timezone.utc) - timedelta(days=20)).isoformat()
    assert (
        calculate_initiative_health(
            {"status": "active", "updated_at": stale_date, "target_date": (today + timedelta(days=30)).isoformat()}
        )
        == "yellow"
    )
    assert (
        calculate_initiative_health(
            {
                "status": "active",
                "updated_at": datetime.now(timezone.utc).isoformat(),
                "target_date": (today + timedelta(days=30)).isoformat(),
            }
        )
        == "green"
    )


def test_initiative_crud(sqlite_engine):
    iid = record_initiative(
        title="Reduce AWS spend",
        description="Remove unused resources",
        status="active",
        priority="high",
        owner="Carlos",
        progress_pct=25,
    )
    assert iid

    row = list_initiatives(limit=10)[0]
    assert row["title"] == "Reduce AWS spend"
    assert row["status"] == "active"
    assert row["health"] in ("green", "yellow", "red")

    update_initiative(initiative_id=iid, progress_pct=50, status="blocked", blocked_reason="Awaiting approval")
    updated = list_initiatives(limit=10)[0]
    assert updated["status"] == "blocked"
    assert updated["health"] == "red"
    assert updated["blocked_reason"] == "Awaiting approval"


def test_execution_review_counts(sqlite_engine):
    today = datetime.now(timezone.utc).date()
    record_initiative(title="Active one", status="active", target_date=(today + timedelta(days=10)).isoformat())
    record_initiative(title="Blocked one", status="blocked", blocked_reason="test")
    record_initiative(
        title="Overdue one",
        status="active",
        target_date=(today - timedelta(days=3)).isoformat(),
    )

    review = get_execution_review()
    assert review["active"] >= 1
    assert review["blocked"] >= 1
    assert review["overdue"] >= 1
    assert review.get("top_risk")


def test_seed_sample_initiatives(sqlite_engine):
    created = seed_sample_initiatives()
    assert len(created) == 5
    assert len(seed_sample_initiatives()) == 0

    titles = {i["title"] for i in list_initiatives(limit=20)}
    assert "Fix portfolio reconciliation" in titles
    assert "Secure exposed security groups" in titles


def test_chief_of_staff_includes_execution_review(sqlite_engine):
    seed_sample_initiatives()

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS), patch(
        "app.jarvis.mvp.chief_of_staff.list_audit_runs", return_value=[]
    ), patch("app.jarvis.mvp.chief_of_staff.list_crypto_audit_runs", return_value=[]), patch(
        "app.jarvis.mvp.chief_of_staff.list_action_plans", return_value=[]
    ), patch("app.jarvis.mvp.chief_of_staff.get_decision_history_index", return_value={}), patch(
        "app.jarvis.mvp.chief_of_staff.generate_lessons_learned", return_value=[]
    ), patch(
        "app.jarvis.mvp.chief_of_staff.get_decision_analytics",
        return_value={"total_decisions": 0, "decision_success_rate": 0},
    ):
        report = generate_executive_report()

    assert "execution_review" in report
    assert report["execution_review"]["active"] >= 1
    assert report["execution_review"]["blocked"] >= 1
    assert report["execution_review"]["overdue"] >= 1
    assert "execution_status" in report
    assert report["execution_status"]["summary"]["active"] >= 1


def test_executive_report_persistence_stores_execution_review(sqlite_engine):
    seed_sample_initiatives()
    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS), patch(
        "app.jarvis.mvp.chief_of_staff.list_audit_runs", return_value=[]
    ), patch("app.jarvis.mvp.chief_of_staff.list_crypto_audit_runs", return_value=[]), patch(
        "app.jarvis.mvp.chief_of_staff.list_action_plans", return_value=[]
    ), patch("app.jarvis.mvp.chief_of_staff.get_decision_history_index", return_value={}), patch(
        "app.jarvis.mvp.chief_of_staff.generate_lessons_learned", return_value=[]
    ), patch(
        "app.jarvis.mvp.chief_of_staff.get_decision_analytics",
        return_value={"total_decisions": 0, "decision_success_rate": 0},
    ):
        report = generate_executive_report()

    record_executive_report(report=report)
    stored = get_executive_report(report["report_id"])
    assert stored is not None
    assert stored["execution_review"]["active"] >= 1
    assert stored["execution_review"].get("top_risk")


def test_executive_dashboard_includes_execution(sqlite_engine):
    seed_sample_initiatives()
    with patch("app.jarvis.mvp.metrics_persistence.collect_daily_metrics", return_value=MOCK_METRICS), patch(
        "app.jarvis.mvp.metrics_persistence.list_daily_metrics", return_value=[]
    ), patch(
        "app.jarvis.mvp.decision_analytics.get_decision_analytics",
        return_value={"decision_success_rate": 0, "approved_count": 0, "rejected_count": 0},
    ):
        dashboard = get_executive_dashboard()

    assert "execution" in dashboard
    assert dashboard["execution"]["active_initiatives"] >= 1
    assert dashboard["execution"]["blocked_initiatives"] >= 1


def test_initiative_confidence_adjustments(sqlite_engine):
    create_initiative(title="Fix portfolio reconciliation", status="completed")
    create_initiative(title="Fix portfolio reconciliation", status="completed")
    create_initiative(title="Failed rollout", status="cancelled")
    create_initiative(title="Failed rollout", status="blocked", blocked_reason="stuck")

    index = get_initiative_outcome_index()
    boosted = apply_initiative_confidence_adjustments(
        {"title": "Fix portfolio reconciliation", "priority_score": 10.0, "impact": 5},
        index,
    )
    lowered = apply_initiative_confidence_adjustments(
        {"title": "Failed rollout", "priority_score": 10.0, "impact": 5},
        index,
    )
    assert boosted["priority_score"] > 10.0
    assert lowered["priority_score"] < 10.0


def test_is_initiative_overdue_ignores_completed(sqlite_engine):
    today = datetime.now(timezone.utc).date()
    initiative = {
        "status": "completed",
        "target_date": (today - timedelta(days=10)).isoformat(),
    }
    assert not is_initiative_overdue(initiative)
