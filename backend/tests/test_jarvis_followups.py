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
        source_id="init-1:overdue",
        title="Portfolio reconciliation is overdue.",
        description="Initiative target date has passed (11 day(s) overdue).",
        severity="high",
    )
    # Day count advanced — title would have changed under the old key; must reuse row.
    fid2 = upsert_followup(
        source_type="initiative",
        source_id="init-1:overdue",
        title="Portfolio reconciliation is overdue.",
        description="Initiative target date has passed (12 day(s) overdue).",
        severity="high",
    )
    assert fid1 == fid2

    row = find_open_followup(
        source_type="initiative",
        source_id="init-1:overdue",
    )
    assert row is not None
    assert row["reminder_count"] == 2
    assert "12 day(s)" in (row.get("description") or "")

    open_items = list_followups(status="open")
    assert len(open_items) == 1


def test_dedupe_ignores_day_count_title_churn(sqlite_engine):
    """Historical bug: title embedded N days → new open row every day → High:66 spam."""
    fid1 = upsert_followup(
        source_type="aws_audit",
        source_id="aws_audit",
        title="AWS audit has not been rerun recently.",
        description="last run 41 days ago",
        severity="high",
    )
    fid2 = upsert_followup(
        source_type="aws_audit",
        source_id="aws_audit",
        title="AWS audit has not been rerun recently.",
        description="last run 42 days ago",
        severity="high",
    )
    assert fid1 == fid2
    assert len(list_followups(status="open")) == 1

    # Simulate legacy orphans with day-count titles / old source_ids, then cleanup.
    from app.jarvis.mvp.followup_persistence import dismiss_legacy_day_count_followup_churn
    from sqlalchemy import text
    from app.database import engine

    assert engine is not None
    with engine.begin() as conn:
        conn.execute(
            text(
                """
                INSERT INTO jarvis_followups (
                    followup_id, source_type, source_id, title, description,
                    severity, status, reminder_count
                ) VALUES
                ('legacy-1', 'aws_audit', 'old-audit-uuid',
                 'AWS audit has not been rerun in 41 days.', '', 'high', 'open', 1),
                ('legacy-2', 'aws_audit', 'old-audit-uuid-2',
                 'AWS audit has not been rerun in 42 days.', '', 'high', 'open', 1)
                """
            )
        )
    assert len(list_followups(status="open")) == 3
    dismissed = dismiss_legacy_day_count_followup_churn()
    assert dismissed == 2
    remaining = list_followups(status="open")
    assert len(remaining) == 1
    assert remaining[0]["source_id"] == "aws_audit"


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
        {
            "severity": "critical",
            "title": "Portfolio reconciliation is overdue.",
            "reminder_count": 2,
            "source_type": "initiative",
            "source_id": "init-1:overdue",
            "status": "open",
        },
        {
            "severity": "high",
            "title": "Security group remediation is blocked.",
            "reminder_count": 1,
            "source_type": "initiative",
            "source_id": "init-2:blocked",
            "status": "open",
        },
        {
            "severity": "high",
            "title": "Action plan 42f2d87b is still awaiting review.",
            "reminder_count": 1,
            "source_type": "action_plan",
            "source_id": "plan-1",
            "status": "open",
        },
    ]
    message = format_followup_daily_alert(summary=summary, followups=followups)

    assert "JARVIS FOLLOW-UP ALERT" in message
    assert "Critical: 1" in message
    assert "High: 2" in message
    assert "Overdue: 1" in message
    assert "Top follow-ups:" in message
    assert "No actions executed." in message
    assert "Portfolio reconciliation" in message


def test_followup_telegram_quiet_when_no_actionable(sqlite_engine):
    from app.jarvis.mvp.telegram_followup_alerts import should_send_followup_daily_alert

    summary = {
        "critical_followups": 0,
        "high_followups": 0,
        "overdue_followups": 0,
    }
    assert should_send_followup_daily_alert(summary=summary, followups=[]) is False

    summary_high = {
        "critical_followups": 0,
        "high_followups": 1,
        "overdue_followups": 0,
    }
    followups = [
        {
            "severity": "high",
            "title": "AWS audit has not been rerun recently.",
            "source_type": "aws_audit",
            "source_id": "aws_audit",
            "status": "open",
        }
    ]
    assert should_send_followup_daily_alert(summary=summary_high, followups=followups) is True

    summary_overdue = {
        "critical_followups": 0,
        "high_followups": 0,
        "overdue_followups": 1,
    }
    assert should_send_followup_daily_alert(summary=summary_overdue, followups=[]) is True


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
