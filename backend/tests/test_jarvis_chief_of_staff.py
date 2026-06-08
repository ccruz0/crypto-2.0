"""Tests for Jarvis Chief of Staff Agent (prioritization only, no execution)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from app.database import (
    ensure_jarvis_action_plans_table,
    ensure_jarvis_audit_runs_table,
    ensure_jarvis_crypto_audit_runs_table,
    ensure_jarvis_executive_reports_table,
)
from app.jarvis.mvp.audit_persistence import record_audit_run
from app.jarvis.mvp.chief_of_staff import (
    _priority_score,
    calculate_health_score,
    generate_executive_report,
)
from app.jarvis.mvp.crypto_audit_persistence import record_crypto_audit_run
from app.jarvis.mvp.executive_report_persistence import (
    get_executive_report,
    list_executive_reports,
    record_executive_report,
    report_generated_within_days,
)
from app.jarvis.mvp.executive_report_service import create_executive_report
from app.jarvis.mvp.telegram_executive_report_alerts import (
    format_weekly_executive_report_alert,
    send_weekly_executive_report_alert,
)

AWS_AUDIT_OUTPUT = {
    "summary": {"read_only": True, "tools_succeeded": 7},
    "cost_findings": [
        {
            "severity": "high",
            "category": "ebs",
            "finding": "3 unattached EBS volume(s)",
            "estimated_monthly_savings_usd": 12.5,
        }
    ],
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
    "recommendations": ["Delete unattached volumes."],
    "estimated_monthly_savings": 12.5,
}

CRYPTO_AUDIT_OUTPUT = {
    "summary": {
        "read_only": True,
        "reconciliation_status": "critical",
        "exchange_total_usd": 10000.0,
        "dashboard_total_usd": 8000.0,
        "total_findings": 2,
    },
    "wallet_findings": [
        {
            "type": "balance_mismatch",
            "severity": "critical",
            "currency": "USD",
            "finding": "Portfolio difference exceeds threshold",
        }
    ],
    "position_findings": [],
    "valuation_findings": [],
    "price_feed_findings": [],
    "recommendations": ["Refresh portfolio cache."],
    "portfolio_difference_usd": 2000.0,
    "portfolio_difference_pct": 20.0,
}

MOCK_METRICS = {
    "metric_date": "2026-06-08",
    "open_findings": 5,
    "critical_findings": 2,
    "portfolio_difference_pct": 20.0,
    "read_only": True,
}


@pytest.fixture
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.executive_report_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.audit_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.crypto_audit_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.action_plan_persistence.engine", eng)
    assert ensure_jarvis_audit_runs_table(eng)
    assert ensure_jarvis_crypto_audit_runs_table(eng)
    assert ensure_jarvis_action_plans_table(eng)
    assert ensure_jarvis_executive_reports_table(eng)
    return eng


def test_priority_score_formula():
    assert _priority_score(9, 10, 2) == 45.0
    assert _priority_score(2, 2, 5) == 0.8


def test_generate_executive_report_structure(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)
    record_crypto_audit_run(task_id="task-2", audit_output=CRYPTO_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        report = generate_executive_report()

    assert report["report_id"]
    assert report["generated_at"]
    assert 0 <= report["overall_health_score"] <= 100
    assert len(report["top_priorities"]) >= 1
    assert report["read_only"] is True
    assert report["execution_performed"] is False

    top = report["top_priorities"][0]
    assert "priority" in top
    assert "title" in top
    assert "reason" in top
    assert "expected_impact" in top
    assert "estimated_savings_usd" in top
    assert "risk_if_ignored" in top


def test_security_group_ranks_high(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        report = generate_executive_report()

    titles = [p["title"] for p in report["top_priorities"]]
    assert any("security group" in t.lower() for t in titles)


def test_health_score_decreases_with_findings():
    healthy = calculate_health_score(
        scored_items=[],
        metrics={"portfolio_difference_pct": 0, "open_findings": 0},
        aws_audit_age_days=1,
        crypto_audit_age_days=1,
        proposed_plan_count=0,
    )
    unhealthy = calculate_health_score(
        scored_items=[
            {"impact": 9, "risk": 10},
            {"impact": 9, "risk": 9},
            {"impact": 7, "risk": 8},
        ],
        metrics={"portfolio_difference_pct": 20, "open_findings": 15},
        aws_audit_age_days=None,
        crypto_audit_age_days=None,
        proposed_plan_count=3,
    )
    assert healthy > unhealthy
    assert 0 <= unhealthy <= 100


def test_persistence_round_trip(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        report = generate_executive_report()

    record_executive_report(report=report)
    stored = get_executive_report(report["report_id"])

    assert stored is not None
    assert stored["report_id"] == report["report_id"]
    assert stored["overall_health_score"] == report["overall_health_score"]
    assert len(stored["top_priorities"]) == len(report["top_priorities"])


def test_list_executive_reports(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        report = generate_executive_report()
    record_executive_report(report=report)

    summaries = list_executive_reports(limit=10)
    assert len(summaries) == 1
    assert summaries[0]["report_id"] == report["report_id"]
    assert summaries[0]["overall_health_score"] == report["overall_health_score"]


def test_create_executive_report_service(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        with patch(
            "app.jarvis.mvp.executive_report_service.send_weekly_executive_report_alert",
            return_value=True,
        ):
            stored = create_executive_report(skip_if_recent=False, send_telegram=True)

    assert stored["report_id"]
    assert get_executive_report(stored["report_id"]) is not None


def test_weekly_dedup(sqlite_engine):
    record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS):
        with patch(
            "app.jarvis.mvp.executive_report_service.send_weekly_executive_report_alert",
            return_value=False,
        ):
            first = create_executive_report(skip_if_recent=False, send_telegram=False)
            second = create_executive_report(skip_if_recent=True, send_telegram=False)

    assert not first.get("skipped")
    assert second.get("skipped") is True
    assert report_generated_within_days(days=6) is True


def test_telegram_format():
    report = {
        "overall_health_score": 81,
        "total_potential_savings_usd": 42.50,
        "top_priorities": [
            {"priority": 1, "title": "Restrict open security groups", "estimated_savings_usd": 0},
            {"priority": 2, "title": "Resolve portfolio mismatch", "estimated_savings_usd": 0},
            {"priority": 3, "title": "Tag production resources", "estimated_savings_usd": 42.50},
        ],
    }
    message = format_weekly_executive_report_alert(report)
    assert "JARVIS WEEKLY REPORT" in message
    assert "Health Score: 81" in message
    assert "Restrict open security groups" in message
    assert "$42.50/month" in message
    assert "No actions executed." in message


def test_telegram_send_no_chat_id():
    with patch.dict("os.environ", {}, clear=True):
        assert send_weekly_executive_report_alert({"overall_health_score": 80}) is False
