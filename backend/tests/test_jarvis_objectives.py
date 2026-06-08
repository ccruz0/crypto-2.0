"""Tests for Jarvis Strategic Objectives layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from app.database import (
    ensure_jarvis_executive_reports_table,
    ensure_jarvis_initiatives_table,
    ensure_jarvis_key_results_table,
    ensure_jarvis_objective_links_table,
    ensure_jarvis_objective_metrics_table,
    ensure_jarvis_objectives_table,
)
from app.jarvis.mvp.chief_of_staff import generate_executive_report
from app.jarvis.mvp.decision_analytics import get_decision_analytics
from app.jarvis.mvp.executive_report_persistence import get_executive_report, record_executive_report
from app.jarvis.mvp.metrics_persistence import get_executive_dashboard
from app.jarvis.mvp.objective_analytics import get_objective_analytics
from app.jarvis.mvp.objective_persistence import (
    calculate_kr_progress,
    calculate_objective_health,
    compute_objective_progress,
    get_strategic_alignment,
    list_objective_metric_trend,
    record_key_result,
    record_objective,
)
from app.jarvis.mvp.objective_service import seed_sample_objectives

MOCK_METRICS = {
    "metric_date": "2026-06-08",
    "open_findings": 2,
    "critical_findings": 2,
    "portfolio_difference_pct": 6.0,
    "read_only": True,
}


@pytest.fixture
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    modules = [
        "app.database",
        "app.jarvis.mvp.objective_persistence",
        "app.jarvis.mvp.initiative_persistence",
        "app.jarvis.mvp.executive_report_persistence",
    ]
    for mod in modules:
        monkeypatch.setattr(f"{mod}.engine", eng)

    assert ensure_jarvis_objectives_table(eng)
    assert ensure_jarvis_key_results_table(eng)
    assert ensure_jarvis_objective_links_table(eng)
    assert ensure_jarvis_objective_metrics_table(eng)
    assert ensure_jarvis_initiatives_table(eng)
    assert ensure_jarvis_executive_reports_table(eng)
    return eng


def test_kr_progress_and_health_rules(sqlite_engine):
    assert calculate_kr_progress(target_value=120, current_value=168, direction="min") < 80
    assert calculate_kr_progress(target_value=99, current_value=75, direction="max") < 80
    assert calculate_kr_progress(target_value=0, current_value=0, direction="min") == 100

    assert calculate_objective_health({"status": "active", "progress_pct": 85, "target_date": "2099-01-01"}) == "green"
    assert calculate_objective_health({"status": "active", "progress_pct": 65, "target_date": "2099-01-01"}) == "yellow"
    assert calculate_objective_health({"status": "active", "progress_pct": 40, "target_date": "2099-01-01"}) == "red"
    assert calculate_objective_health(
        {"status": "active", "progress_pct": 90, "target_date": "2020-01-01"},
    ) == "red"


def test_objective_crud_and_progress(sqlite_engine):
    oid = record_objective(title="Reduce AWS spend", status="active", owner="Carlos")
    record_key_result(
        objective_id=oid,
        title="Monthly AWS spend below $120",
        target_value=120,
        current_value=168,
        unit="USD",
        direction="min",
    )
    record_key_result(
        objective_id=oid,
        title="Zero unattached EBS",
        target_value=0,
        current_value=0,
        unit="count",
        direction="min",
    )

    progress = compute_objective_progress(oid)
    assert 0 < progress < 100

    trend = list_objective_metric_trend(objective_id=oid, days=30)
    assert isinstance(trend, list)


def test_seed_sample_objectives(sqlite_engine):
    result = seed_sample_objectives()
    assert result["count"] >= 3
    assert result["execution_performed"] is False

    titles = [o["title"] for o in result["objectives"]]
    assert "Reduce AWS spend" in titles
    assert "Improve portfolio accuracy" in titles
    assert "Improve security posture" in titles

    for obj in result["objectives"]:
        assert len(obj.get("key_results") or []) >= 2


def test_strategic_alignment(sqlite_engine):
    seed_sample_objectives()
    alignment = get_strategic_alignment()

    assert alignment["summary"]["total_objectives"] >= 3
    assert len(alignment["objectives"]) >= 1
    aws_obj = next((o for o in alignment["objectives"] if "AWS" in str(o.get("title"))), None)
    assert aws_obj is not None
    assert "progress_pct" in aws_obj
    assert "supporting_initiatives" in aws_obj


def test_executive_dashboard_objectives(sqlite_engine):
    seed_sample_objectives()

    with patch("app.jarvis.mvp.metrics_persistence.collect_daily_metrics", return_value=MOCK_METRICS):
        dashboard = get_executive_dashboard()

    strategic = dashboard.get("strategic_objectives") or {}
    assert strategic.get("total_objectives", 0) >= 3
    assert "average_progress_pct" in strategic


def test_chief_of_staff_strategic_alignment(sqlite_engine):
    seed_sample_objectives()

    with (
        patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS),
        patch("app.jarvis.mvp.chief_of_staff.list_audit_runs", return_value=[]),
        patch("app.jarvis.mvp.chief_of_staff.list_crypto_audit_runs", return_value=[]),
        patch("app.jarvis.mvp.chief_of_staff.list_action_plans", return_value=[]),
    ):
        report = generate_executive_report()

    alignment = report.get("strategic_alignment") or {}
    assert len(alignment.get("objectives") or []) >= 1
    assert alignment.get("summary", {}).get("total_objectives", 0) >= 3


def test_executive_report_persistence_strategic_alignment(sqlite_engine):
    seed_sample_objectives()

    with (
        patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS),
        patch("app.jarvis.mvp.chief_of_staff.list_audit_runs", return_value=[]),
        patch("app.jarvis.mvp.chief_of_staff.list_crypto_audit_runs", return_value=[]),
        patch("app.jarvis.mvp.chief_of_staff.list_action_plans", return_value=[]),
    ):
        report = generate_executive_report()

    record_executive_report(report=report)
    stored = get_executive_report(report["report_id"])
    assert stored is not None
    assert len(stored.get("strategic_alignment", {}).get("objectives") or []) >= 1


def test_decision_intelligence_objective_outcomes(sqlite_engine):
    seed_sample_objectives()
    analytics = get_objective_analytics()
    assert analytics["total_objectives"] >= 3

    decision_intel = get_decision_analytics()
    outcomes = decision_intel.get("objective_outcomes") or {}
    assert outcomes.get("total_objectives", 0) >= 3
