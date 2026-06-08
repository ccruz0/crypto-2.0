"""Tests for Jarvis Action Planner (recommendations only, no execution)."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from app.database import ensure_jarvis_action_plans_table, ensure_jarvis_audit_runs_table
from app.jarvis.mvp.action_plan_persistence import (
    get_action_plan,
    list_action_plans,
    record_action_plan,
)
from app.jarvis.mvp.action_plan_service import create_action_plan_from_audit
from app.jarvis.mvp.action_planner import generate_action_plan
from app.jarvis.mvp.audit_persistence import record_audit_run
from app.jarvis.mvp.crypto_audit_persistence import record_crypto_audit_run
from app.jarvis.mvp.telegram_action_plan_alerts import format_action_plan_alert, send_action_plan_alert


@pytest.fixture
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    monkeypatch.setattr("app.database.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.action_plan_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.audit_persistence.engine", eng)
    monkeypatch.setattr("app.jarvis.mvp.crypto_audit_persistence.engine", eng)
    assert ensure_jarvis_audit_runs_table(eng)
    assert ensure_jarvis_action_plans_table(eng)
    from app.database import ensure_jarvis_crypto_audit_runs_table

    assert ensure_jarvis_crypto_audit_runs_table(eng)
    return eng


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
            "required_tags": ["Environment", "Project", "Owner"],
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
            "type": "missing_asset",
            "severity": "critical",
            "currency": "ETH",
            "finding": "ETH present on exchange but missing in dashboard cache",
        }
    ],
    "position_findings": [],
    "valuation_findings": [],
    "price_feed_findings": [],
    "recommendations": ["Refresh portfolio cache."],
    "portfolio_difference_usd": 2000.0,
    "portfolio_difference_pct": 20.0,
}


def test_generate_aws_action_plan_structure(sqlite_engine):
    audit_id = record_audit_run(task_id="task-1", audit_output=AWS_AUDIT_OUTPUT)
    plan = generate_action_plan(source_type="aws_audit", source_id=audit_id)

    assert plan["source_type"] == "aws_audit"
    assert plan["source_id"] == audit_id
    assert plan["severity"] == "high"
    assert plan["estimated_savings_usd"] == pytest.approx(12.5)
    assert plan["execution_performed"] is False
    assert plan["read_only"] is True
    assert len(plan["actions"]) >= 3

    titles = [a["title"] for a in plan["actions"]]
    assert any("EBS" in t for t in titles)
    assert any("security group" in t.lower() for t in titles)
    assert any("tag" in t.lower() for t in titles)

    for action in plan["actions"]:
        assert action["title"]
        assert action["description"]
        assert action["impact"]
        assert action["risk"]
        assert len(action["manual_steps"]) >= 1


def test_generate_crypto_action_plan_critical_severity(sqlite_engine):
    audit_id = record_crypto_audit_run(task_id="task-2", audit_output=CRYPTO_AUDIT_OUTPUT)
    plan = generate_action_plan(source_type="crypto_audit", source_id=audit_id)

    assert plan["severity"] == "critical"
    assert plan["estimated_savings_usd"] == 0.0
    assert plan["execution_performed"] is False
    assert any("missing asset" in a["title"].lower() or "exchange sync" in a["title"].lower() for a in plan["actions"])


def test_generate_action_plan_not_found():
    with pytest.raises(ValueError, match="not found"):
        generate_action_plan(source_type="aws_audit", source_id="nonexistent-id")


def test_persist_and_list_action_plans(sqlite_engine):
    audit_id = record_audit_run(task_id="task-3", audit_output=AWS_AUDIT_OUTPUT)
    stored = create_action_plan_from_audit(source_type="aws_audit", source_id=audit_id)

    assert stored["status"] == "proposed"
    assert stored["plan_id"]

    fetched = get_action_plan(stored["plan_id"])
    assert fetched is not None
    assert fetched["plan_id"] == stored["plan_id"]
    assert fetched["execution_performed"] is False
    assert len(fetched["actions"]) >= 1

    plans = list_action_plans(limit=10)
    assert len(plans) == 1
    assert plans[0]["plan_id"] == stored["plan_id"]
    assert plans[0]["severity"] == "high"


def test_telegram_alert_only_for_critical():
    critical_plan = {
        "plan_id": "plan-1",
        "severity": "critical",
        "estimated_savings_usd": 0,
        "finding_summary": "ETH present on exchange but missing in dashboard cache",
    }
    high_plan = {
        "plan_id": "plan-2",
        "severity": "high",
        "estimated_savings_usd": 12.5,
        "finding_summary": "Unattached EBS volumes",
    }

    message = format_action_plan_alert(critical_plan)
    assert "ACTION PLAN GENERATED" in message
    assert "CRITICAL" in message
    assert "Review required" in message
    assert "No execution performed" in message

    with patch("app.jarvis.mvp.telegram_action_plan_alerts._chat_id", return_value="12345"):
        with patch("app.jarvis.telegram_service.TelegramMissionService") as mock_svc:
            mock_svc.return_value.send_message.return_value = True
            assert send_action_plan_alert(critical_plan) is True
            mock_svc.return_value.send_message.assert_called_once()

            mock_svc.return_value.send_message.reset_mock()
            assert send_action_plan_alert(high_plan) is False
            mock_svc.return_value.send_message.assert_not_called()


def test_create_action_plan_sends_critical_telegram(sqlite_engine):
    audit_id = record_crypto_audit_run(task_id="task-4", audit_output=CRYPTO_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.action_plan_service.send_action_plan_alert", return_value=True) as mock_alert:
        plan = create_action_plan_from_audit(source_type="crypto_audit", source_id=audit_id)

    assert plan["severity"] == "critical"
    mock_alert.assert_called_once()
    alert_arg = mock_alert.call_args[0][0]
    assert alert_arg["severity"] == "critical"


def test_no_execution_tools_invoked(sqlite_engine):
    """Action planner must not call auditor tools or write AWS/crypto APIs."""
    audit_id = record_audit_run(task_id="task-5", audit_output=AWS_AUDIT_OUTPUT)

    with patch("app.jarvis.mvp.aws_auditor.run_aws_audit") as mock_aws:
        with patch("app.jarvis.mvp.crypto_auditor.run_crypto_audit") as mock_crypto:
            plan = create_action_plan_from_audit(source_type="aws_audit", source_id=audit_id)

    mock_aws.assert_not_called()
    mock_crypto.assert_not_called()
    assert plan["execution_performed"] is False
    assert plan["read_only"] is True


def test_generate_executive_dashboard_action_plan():
    dashboard = {
        "infrastructure": {"aws_monthly_spend": 250.0},
        "security": {"open_findings": 4, "critical_findings": 1, "security_groups_exposed_0_0_0_0": 2, "untagged_resources": 3},
        "jarvis_activity": {"failed_tasks": 2},
        "crypto_health": {"difference_pct": 8.5, "reconciliation_status": "mismatch"},
        "read_only": True,
    }
    with patch("app.jarvis.mvp.metrics_persistence.get_executive_dashboard", return_value=dashboard):
        plan = generate_action_plan(source_type="executive_dashboard", source_id="current")

    assert plan["source_type"] == "executive_dashboard"
    assert plan["severity"] in ("critical", "high")
    assert plan["execution_performed"] is False
    assert len(plan["actions"]) >= 2


def test_record_action_plan_direct(sqlite_engine):
    plan = {
        "plan_id": "direct-plan-1",
        "source_type": "aws_audit",
        "source_id": "audit-x",
        "severity": "medium",
        "estimated_savings_usd": 5.0,
        "estimated_risk_reduction": "test",
        "actions": [
            {
                "title": "Test action",
                "description": "desc",
                "impact": "impact",
                "risk": "low",
                "manual_steps": ["step 1"],
            }
        ],
    }
    pid = record_action_plan(plan=plan, status="proposed")
    assert pid == "direct-plan-1"
    row = get_action_plan(pid)
    assert row is not None
    assert row["status"] == "proposed"
    assert row["action_count"] == 1
