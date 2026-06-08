"""Tests for Jarvis executive daily metrics (read-only)."""

from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

from app.jarvis.mvp.metrics_persistence import collect_daily_metrics, get_executive_dashboard


@patch("app.jarvis.mvp.metrics_persistence._fetch_crypto_health")
@patch("app.jarvis.mvp.metrics_persistence._fetch_jarvis_activity")
@patch("app.jarvis.mvp.metrics_persistence._fetch_security_metrics")
@patch("app.jarvis.mvp.metrics_persistence._fetch_aws_resource_counts")
@patch("app.jarvis.mvp.metrics_persistence._fetch_aws_monthly_cost", return_value=100.0)
@patch("app.jarvis.mvp.metrics_persistence._fetch_aws_daily_cost", return_value=5.0)
@patch("app.jarvis.mvp.metrics_persistence.ensure_jarvis_daily_metrics_table", return_value=False)
def test_collect_daily_metrics_read_only(
    _ensure_table,
    _daily,
    _monthly,
    mock_resources,
    mock_security,
    mock_jarvis,
    mock_crypto,
):
    mock_resources.return_value = {
        "ec2_count": 2,
        "ebs_count": 5,
        "snapshot_count": 10,
        "eip_count": 1,
    }
    mock_security.return_value = {
        "open_findings": 3,
        "critical_findings": 1,
        "sg_exposed_0_0_0_0": 2,
        "untagged_resources": 4,
        "last_aws_audit_date": "2026-06-01T00:00:00Z",
    }
    mock_jarvis.return_value = {
        "task_count": 10,
        "audit_count": 2,
        "task_success_rate": 90.0,
        "failed_tasks": 1,
        "avg_task_cost": 0.01,
        "bedrock_cost": 0.1,
    }
    mock_crypto.return_value = {
        "last_reconciliation_date": None,
        "dashboard_portfolio_value": 5000.0,
        "exchange_portfolio_value": 5100.0,
        "portfolio_difference_pct": 1.96,
        "reconciliation_status": "mismatch",
    }

    metrics = collect_daily_metrics(metric_date=date(2026, 6, 8))
    assert metrics["aws_monthly_cost"] == 100.0
    assert metrics["ec2_count"] == 2
    assert metrics["task_count"] == 10
    assert metrics["dashboard_portfolio_value"] == 5000.0
    assert metrics["read_only"] is True


@patch("app.jarvis.mvp.metrics_persistence.collect_daily_metrics")
@patch("app.jarvis.mvp.metrics_persistence.list_daily_metrics", return_value=[])
def test_get_executive_dashboard_structure(mock_trends, mock_collect):
    mock_collect.return_value = {
        "aws_monthly_cost": 50.0,
        "aws_daily_cost": 2.0,
        "ec2_count": 1,
        "ebs_count": 2,
        "snapshot_count": 3,
        "eip_count": 0,
        "open_findings": 1,
        "critical_findings": 0,
        "sg_exposed_0_0_0_0": 0,
        "untagged_resources": 0,
        "last_aws_audit_date": None,
        "task_count": 5,
        "audit_count": 1,
        "task_success_rate": 100.0,
        "failed_tasks": 0,
        "avg_task_cost": 0.005,
        "bedrock_cost": 0.05,
        "dashboard_portfolio_value": 1000.0,
        "exchange_portfolio_value": 1000.0,
        "portfolio_difference_pct": 0.0,
        "last_reconciliation_date": None,
        "reconciliation_status": "pass",
        "read_only": True,
    }
    dashboard = get_executive_dashboard()
    assert "infrastructure" in dashboard
    assert "security" in dashboard
    assert "jarvis_activity" in dashboard
    assert "crypto_health" in dashboard
    assert "trends" in dashboard
    assert dashboard["read_only"] is True
