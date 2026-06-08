"""Tests for Jarvis Follow-up Agent (read-only management layer)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, text

from app.database import (
    ensure_jarvis_action_plans_table,
    ensure_jarvis_audit_runs_table,
    ensure_jarvis_crypto_audit_runs_table,
    ensure_jarvis_decisions_table,
    ensure_jarvis_executive_reports_table,
    ensure_jarvis_followups_table,
    ensure_jarvis_initiatives_table,
)
from app.jarvis.mvp.chief_of_staff import generate_executive_report
from app.jarvis.mvp.followup_agent import detect_followups
from app.jarvis.mvp.followup_persistence import (
    find_open_followup,
    get_followup_summary,
    list_followups,
    upsert_followup,
)
from app.jarvis.mvp.followup_service import generate_followups, seed_sample_followup_data
from app.jarvis.mvp.metrics_persistence import get_executive_dashboard
from app.jarvis.mvp.telegram_followup_alerts import format_followup_daily_alert

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
    modules = [
        "app.database",
        "app.jarvis.mvp.followup_persistence",
        "app.jarvis.mvp.initiative_persistence",
        "app.jarvis.mvp.action_plan_persistence",
        "app.jarvis.mvp.decision_persistence",
        "app.jarvis.mvp.audit_persistence",
        "app.jarvis.mvp.crypto_audit_persistence",
        "app.jarvis.mvp.executive_report_persistence",
    ]
    for mod in modules:
        monkeypatch.setattr(f"{mod}.engine", eng)

    assert ensure_jarvis_followups_table(eng)
    assert ensure_jarvis_initiatives_table(eng)
    assert ensure_jarvis_action_plans_table(eng)
    assert ensure_jarvis_decisions_table(eng)
    assert ensure_jarvis_audit_runs_table(eng)
    assert ensure_jarvis_crypto_audit_runs_table(eng)
    assert ensure_jarvis_executive_reports_table(eng)
    return eng


def test_deduplication(sqlite_engine):
    fid1 = upsert_followup(
        source_type="initiative",
        source_id="init-1",
        title="Portfolio reconciliation is overdue by 11 days.",
        severity="high",
    )
    fid2 = upsert_followup(
        source_type="initiative",
        source_id="init-1",
        title="Portfolio reconciliation is overdue by 11 days.",
        severity="high",
    )
    assert fid1 == fid2

    row = find_open_followup(
        source_type="initiative",
        source_id="init-1",
        title="Portfolio reconciliation is overdue by 11 days.",
    )
    assert row is not None
    assert row["reminder_count"] == 2

    open_items = list_followups(status="open")
    assert len(open_items) == 1


def test_followup_rules_with_sample_data(sqlite_engine):
    seed_sample_followup_data()

    result = detect_followups()
    assert result["followups_touched"] >= 4
    assert result["execution_performed"] is False

    open_items = list_followups(status="open", limit=100)
    titles = [f["title"] for f in open_items]

    assert any("Portfolio reconciliation" in t and "overdue" in t for t in titles)
    assert any("Security group remediation" in t and "blocked" in t for t in titles)
    assert any("42f2d87b" in t and "awaiting review" in t for t in titles)
    assert any("unknown outcome" in t for t in titles)

    # Deduplication on second run
    first_count = len(open_items)
    detect_followups()
    second_open = list_followups(status="open", limit=100)
    assert len(second_open) == first_count
    assert all(f["reminder_count"] >= 2 for f in second_open)


def test_executive_dashboard_followup_counts(sqlite_engine):
    upsert_followup(
        source_type="initiative",
        source_id="x",
        title="Critical item",
        severity="critical",
    )
    upsert_followup(
        source_type="initiative",
        source_id="y",
        title="High item",
        severity="high",
    )

    with patch("app.jarvis.mvp.metrics_persistence.collect_daily_metrics", return_value=MOCK_METRICS):
        dashboard = get_executive_dashboard()

    followups = dashboard.get("followups") or {}
    assert followups.get("open_followups") == 2
    assert followups.get("critical_followups") == 1
    assert followups.get("high_followups") == 1


def test_chief_of_staff_followup_review(sqlite_engine):
    upsert_followup(
        source_type="initiative",
        source_id="blocked-1",
        title="Security group remediation is blocked.",
        description="Blocked initiative",
        severity="critical",
    )

    with (
        patch("app.jarvis.mvp.chief_of_staff.collect_daily_metrics", return_value=MOCK_METRICS),
        patch("app.jarvis.mvp.chief_of_staff.list_audit_runs", return_value=[]),
        patch("app.jarvis.mvp.chief_of_staff.list_crypto_audit_runs", return_value=[]),
        patch("app.jarvis.mvp.chief_of_staff.list_action_plans", return_value=[]),
    ):
        report = generate_executive_report()

    review = report.get("followup_review") or {}
    assert review.get("has_high_severity") is True
    assert len(review.get("top_followups") or []) >= 1

    blocked_titles = [b.get("title") for b in report.get("blocked_items") or []]
    assert any("Security group remediation" in t for t in blocked_titles)


def test_telegram_alert_format(sqlite_engine):
    summary = {
        "critical_followups": 1,
        "high_followups": 2,
        "overdue_followups": 1,
    }
    followups = [
        {"severity": "critical", "title": "Portfolio reconciliation is overdue by 11 days.", "reminder_count": 2},
        {"severity": "high", "title": "Security group remediation is blocked.", "reminder_count": 1},
        {"severity": "high", "title": "Action plan 42f2d87b is still awaiting review.", "reminder_count": 1},
    ]
    message = format_followup_daily_alert(summary=summary, followups=followups)

    assert "JARVIS FOLLOW-UP ALERT" in message
    assert "Critical: 1" in message
    assert "High: 2" in message
    assert "Overdue: 1" in message
    assert "Top follow-ups:" in message
    assert "No actions executed." in message
    assert "Portfolio reconciliation" in message


def test_generate_followups_telegram_mock(sqlite_engine):
    seed_sample_followup_data()
    detect_followups()

    with patch(
        "app.jarvis.mvp.followup_service.send_followup_daily_alert",
        return_value=True,
    ) as mock_alert:
        result = generate_followups(send_telegram=True)

    assert result["followups_touched"] >= 1
    assert result["telegram_sent"] is True
    mock_alert.assert_called_once()
