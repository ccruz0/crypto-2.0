"""Tests for Jarvis KR auto-refresh layer."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from app.database import (
    ensure_jarvis_key_results_metric_columns,
    ensure_jarvis_key_results_table,
    ensure_jarvis_kr_refresh_runs_table,
    ensure_jarvis_objective_metrics_table,
    ensure_jarvis_objectives_table,
)
from app.jarvis.mvp.kr_metric_resolver import METRIC_ALIASES, SUPPORTED_METRICS, resolve_metric
from app.jarvis.mvp.kr_refresh_persistence import list_kr_refresh_runs
from app.jarvis.mvp.kr_refresh_service import refresh_key_results
from app.jarvis.mvp.objective_persistence import get_objective, record_key_result, record_objective
from app.jarvis.mvp.telegram_kr_alerts import format_kr_alert


@pytest.fixture
def sqlite_engine(monkeypatch):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    modules = [
        "app.database",
        "app.jarvis.mvp.objective_persistence",
        "app.jarvis.mvp.kr_refresh_persistence",
    ]
    for mod in modules:
        monkeypatch.setattr(f"{mod}.engine", eng)

    assert ensure_jarvis_objectives_table(eng)
    assert ensure_jarvis_key_results_table(eng)
    assert ensure_jarvis_key_results_metric_columns(eng)
    assert ensure_jarvis_objective_metrics_table(eng)
    assert ensure_jarvis_kr_refresh_runs_table(eng)
    return eng


def test_supported_metrics_and_aliases():
    assert "aws_monthly_spend" in SUPPORTED_METRICS
    assert "crypto_reconciliation_accuracy_pct" in SUPPORTED_METRICS
    assert METRIC_ALIASES["unattached_ebs"] == "aws_unattached_ebs_count"
    assert METRIC_ALIASES["critical_findings"] == "_combined_critical_findings"


def test_resolve_metric_aws_monthly_spend():
    with patch("app.jarvis.mvp.metrics_persistence._fetch_aws_monthly_cost", return_value=142.5):
        result = resolve_metric("aws_monthly_spend")

    assert result["error"] is None
    assert result["current_value"] == 142.5
    assert "Cost Explorer" in result["source"]


@patch("app.jarvis.mvp.kr_refresh_service.resolve_metric")
def test_refresh_key_results_updates_kr_and_records_run(mock_resolve, sqlite_engine):
    oid = record_objective(title="Reduce AWS spend", status="active")
    record_key_result(
        objective_id=oid,
        title="Monthly AWS spend below $120",
        metric_name="aws_monthly_spend",
        target_value=120,
        current_value=0,
        unit="USD",
        direction="min",
    )
    mock_resolve.return_value = {
        "metric_name": "aws_monthly_spend",
        "current_value": 95.0,
        "source": "AWS Cost Explorer (30d)",
        "confidence": "high",
        "error": None,
    }

    with patch("app.jarvis.mvp.kr_refresh_service.send_kr_refresh_alerts", return_value=0):
        result = refresh_key_results(send_telegram=False)

    assert result["kr_count"] >= 1
    assert result["updated_count"] >= 1
    assert result["failed_count"] == 0
    assert result["execution_performed"] is False

    runs = list_kr_refresh_runs(limit=1)
    assert len(runs) == 1
    assert runs[0]["refresh_id"] == result["refresh_id"]


def test_refresh_key_results_records_failures(sqlite_engine):
    oid = record_objective(title="Test objective", status="active")
    record_key_result(
        objective_id=oid,
        title="Bad metric KR",
        metric_name="unknown_metric_xyz",
        target_value=10,
        current_value=0,
        direction="max",
    )

    with patch("app.jarvis.mvp.kr_refresh_service.send_kr_refresh_alerts", return_value=0):
        result = refresh_key_results(send_telegram=False)

    assert result["failed_count"] >= 1
    assert any("unknown_metric" in str(e.get("error", "")) for e in result["errors"])


def test_refresh_recalculates_objective_progress(sqlite_engine):
    oid = record_objective(title="Spend objective", status="active")
    record_key_result(
        objective_id=oid,
        title="Monthly spend below 120",
        metric_name="aws_monthly_spend",
        target_value=120,
        current_value=200,
        unit="USD",
        direction="min",
    )

    with (
        patch(
            "app.jarvis.mvp.kr_refresh_service.resolve_metric",
            return_value={
                "metric_name": "aws_monthly_spend",
                "current_value": 100.0,
                "source": "test",
                "confidence": "high",
                "error": None,
            },
        ),
        patch("app.jarvis.mvp.kr_refresh_service.send_kr_refresh_alerts", return_value=0),
    ):
        refresh_key_results(send_telegram=False)

    obj = get_objective(oid)
    assert obj is not None
    assert obj["progress_pct"] > 0
    kr = obj["key_results"][0]
    assert kr["current_value"] == 100.0
    assert kr["metric_source"] == "test"
    assert kr["last_refreshed_at"] is not None


def test_telegram_alert_format():
    message = format_kr_alert(
        objective_title="Reduce AWS spend",
        kr_title="Monthly AWS spend below $120",
        current_value=168,
        target_value=120,
        status="behind",
        unit="USD",
        reason="AWS spend exceeds target",
    )
    assert "JARVIS KR ALERT" in message
    assert "Reduce AWS spend" in message
    assert "No action executed." in message
