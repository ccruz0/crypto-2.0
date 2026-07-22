"""Phase 6B: Autonomous alerting and daily health summary tests."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_jarvis import router as jarvis_router
from app.jarvis.change_execution.config import phase5_safety_status
from app.jarvis.execution.safety import SafetyLevel, classify_text
from app.jarvis.investigations.alerting import config as alert_config
from app.jarvis.investigations.alerting.daily_report import (
    build_daily_report_summary,
    generate_and_store_daily_report,
    maybe_generate_daily_report,
)
from app.jarvis.investigations.alerting.engine import process_investigation_alert, process_task_failure_alert
from app.jarvis.investigations.alerting.fingerprint import build_fingerprint, normalize_finding_text
from app.jarvis.investigations.alerting.persistence import (
    ensure_tables,
    get_alert,
    list_alerts,
    upsert_alert,
)
from app.jarvis.investigations.alerting.severity import classify_investigation_report, classify_task_failure
from app.jarvis.investigations.alerting.telegram import (
    format_daily_health_report_message,
    format_investigation_alert_message,
    should_send_telegram,
)
from app.jarvis.investigations.alerting.types import AlertInput, AlertRecord, AlertSeverity, AlertStatus
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.scheduler.persistence import (
    ScheduledTaskStatus,
    complete_task,
    create_task,
    upsert_schedule,
)


@pytest.fixture()
def alert_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    import app.database as db_mod
    from app.jarvis.investigations.alerting import persistence as alert_persist_mod
    from app.jarvis.investigations.scheduler import persistence as sched_persist_mod

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db_mod.ensure_jarvis_alerting_tables(engine)
    db_mod.ensure_jarvis_scheduled_investigations_tables(engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(alert_persist_mod, "engine", engine)
    monkeypatch.setattr(sched_persist_mod, "engine", engine)
    yield engine
    engine.dispose()


def _fake_report(**kwargs):
    defaults = {
        "investigation_id": "inv-test-1",
        "objective": "Check database health",
        "category": "database",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED,
        "summary": "All checks passed",
        "evidence": [{"source": "db", "detail": "ok", "reference": "health", "confidence": 0.9}],
        "root_cause": None,
        "impact": "",
        "collector_failures": [],
        "resolution_status": None,
    }
    defaults.update(kwargs)
    return type("Report", (), defaults)()


# --- Severity classification ---


def test_classify_info_on_clean_completion():
    report = _fake_report(summary="All checks passed — no issues detected")
    result = classify_investigation_report(report, source="database_health")
    assert result is not None
    assert result.severity == AlertSeverity.INFO
    assert result.alert_type == "investigation_completed"


def test_classify_critical_exchange_unreachable():
    report = _fake_report(
        category="exchange",
        summary="Exchange unreachable — cannot reach exchange API",
        root_cause="Exchange connectivity failed",
    )
    result = classify_investigation_report(report, source="exchange_connectivity")
    assert result is not None
    assert result.severity == AlertSeverity.CRITICAL
    assert result.alert_type == "exchange_unreachable"


def test_classify_warning_reconciliation_mismatch():
    report = _fake_report(
        category="portfolio",
        summary="Portfolio reconciliation mismatch detected between wallet and dashboard",
        root_cause="Wallet mismatch",
    )
    result = classify_investigation_report(report, source="portfolio_reconciliation")
    assert result is not None
    assert result.severity == AlertSeverity.WARNING
    assert result.alert_type == "reconciliation_mismatch"


def test_classify_critical_investigation_failed_status():
    report = _fake_report(status=InvestigationStatus.FAILED, summary="Investigation failed")
    result = classify_investigation_report(report, source="api_health")
    assert result is not None
    assert result.severity == AlertSeverity.CRITICAL
    assert result.alert_type == "investigation_failed"


def test_classify_warning_websocket_instability():
    report = _fake_report(
        category="websocket",
        summary="Websocket prices stale for 5 minutes",
        root_cause="WebSocket disconnect",
    )
    result = classify_investigation_report(report, source="websocket_health")
    assert result is not None
    assert result.severity == AlertSeverity.WARNING


def test_classify_task_failure_is_critical():
    result = classify_task_failure(
        source="scheduler",
        objective="Check health",
        error_message="timeout",
    )
    assert result.severity == AlertSeverity.CRITICAL


# --- Fingerprint / deduplication ---


def test_fingerprint_stable_for_same_finding():
    a = AlertInput(
        alert_type="api_degradation",
        source="api_health",
        title="API degraded",
        summary="API degradation detected",
        severity=AlertSeverity.WARNING,
        normalized_finding="api_degradation api_health api degradation detected",
    )
    b = AlertInput(
        alert_type="api_degradation",
        source="api_health",
        title="API degraded",
        summary="API degradation detected",
        severity=AlertSeverity.WARNING,
        normalized_finding="api_degradation api_health api degradation detected",
    )
    assert build_fingerprint(a) == build_fingerprint(b)


def test_normalize_finding_strips_uuids():
    raw = "issue abc-123-def found at 2026-06-16T08:00:00"
    normalized = normalize_finding_text(raw)
    assert "2026-06-16" not in normalized


def test_alert_deduplication_increments_occurrence(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ALERT_SUPPRESSION_WINDOW_HOURS", "24")
    alert_input = AlertInput(
        alert_type="api_degradation",
        source="api_health",
        title="API degraded",
        summary="API degradation detected",
        severity=AlertSeverity.WARNING,
        normalized_finding="api_degradation api_health degradation",
    )
    fp = build_fingerprint(alert_input)
    first = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)
    second = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=24)
    assert first.alert_id == second.alert_id
    assert second.occurrence_count == 2
    assert second.deduplicated is True


def test_suppression_window_expires(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ALERT_SUPPRESSION_WINDOW_HOURS", "1")
    alert_input = AlertInput(
        alert_type="test",
        source="src",
        title="Test",
        summary="Test alert",
        severity=AlertSeverity.WARNING,
        normalized_finding="test src alert",
    )
    fp = build_fingerprint(alert_input)
    first = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=1)

    from sqlalchemy import text
    import app.jarvis.investigations.alerting.persistence as persist_mod

    stale = datetime.now(timezone.utc) - timedelta(hours=2)
    with alert_db.begin() as conn:
        conn.execute(
            text("UPDATE jarvis_alerts SET last_seen = :stale WHERE alert_id = :aid"),
            {"stale": stale, "aid": first.alert_id},
        )

    second = upsert_alert(alert_input, fingerprint=fp, suppression_window_hours=1)
    assert second.alert_id != first.alert_id


# --- Telegram formatting ---


def test_telegram_format_includes_required_fields():
    alert = AlertRecord(
        alert_id="alert-1",
        created_at="2026-06-16T08:00:00Z",
        severity="CRITICAL",
        source="exchange_connectivity",
        investigation_id="inv-1",
        title="Exchange unreachable",
        summary="Cannot reach exchange",
        evidence=[{"detail": "x"}],
        status="open",
        fingerprint="fp",
        last_seen="2026-06-16T08:00:00Z",
    )
    msg = format_investigation_alert_message(alert, investigation_type="exchange_connectivity")
    assert "CRITICAL" in msg
    assert "exchange_connectivity" in msg
    assert "inv-1" in msg
    assert "Evidence: 1" in msg
    assert "Alert: alert-1" in msg
    assert "CTAs:" in msg


def test_telegram_warning_not_sent_by_default():
    """WARNING findings are stored but do not interrupt via Telegram."""
    alert = AlertRecord(
        alert_id="a",
        created_at="",
        severity="WARNING",
        source="s",
        investigation_id=None,
        title="t",
        summary="s",
        evidence=[],
        status="open",
        fingerprint="f",
    )
    assert should_send_telegram(alert, info_enabled=False) is False
    assert should_send_telegram(alert, info_enabled=True) is False


def test_telegram_critical_sent():
    alert = AlertRecord(
        alert_id="a",
        created_at="",
        severity="CRITICAL",
        source="s",
        investigation_id=None,
        title="t",
        summary="s",
        evidence=[],
        status="open",
        fingerprint="f",
    )
    assert should_send_telegram(alert, info_enabled=False) is True


def test_telegram_info_optional():
    alert = AlertRecord(
        alert_id="a",
        created_at="",
        severity="INFO",
        source="s",
        investigation_id=None,
        title="t",
        summary="s",
        evidence=[],
        status="open",
        fingerprint="f",
    )
    assert should_send_telegram(alert, info_enabled=False) is False
    assert should_send_telegram(alert, info_enabled=True) is True


def test_daily_report_telegram_format():
    msg = format_daily_health_report_message(
        {
            "report_date": "2026-06-16",
            "investigations_executed": 10,
            "success_rate_pct": 90.0,
            "failures": 1,
            "warnings": 2,
            "critical_alerts": 0,
            "average_runtime_ms": 1500,
            "top_recurring_issues": [{"title": "API degradation", "occurrence_count": 3}],
        }
    )
    assert "JARVIS DAILY HEALTH SUMMARY" in msg
    assert "90.0%" in msg
    assert "API degradation" in msg


# --- Alert engine ---


def test_process_investigation_alert_persists(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ALERTING_ENABLED", "true")
    with patch("app.jarvis.investigations.alerting.engine.send_investigation_alert", return_value=True):
        report = _fake_report(summary="All checks passed — healthy")
        record = process_investigation_alert(report, source="database_health")
    assert record is not None
    assert record.severity == AlertSeverity.INFO.value
    stored = get_alert(record.alert_id)
    assert stored is not None


def test_process_task_failure_alert(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ALERTING_ENABLED", "true")
    with patch("app.jarvis.investigations.alerting.engine.send_investigation_alert", return_value=True):
        record = process_task_failure_alert(
            source="api_health",
            objective="Check API",
            error_message="blocked",
        )
    assert record is not None
    assert record.severity == AlertSeverity.CRITICAL.value


# --- Daily report ---


def test_daily_report_generation(alert_db):
    upsert_schedule(
        schedule_id="api_health",
        template_id="jarvis_task_failing",
        title="API health",
        objective="Why is Jarvis task failing?",
        category="api",
    )
    task = create_task(
        schedule_id="api_health",
        template_id="jarvis_task_failing",
        objective="Why is Jarvis task failing?",
    )
    complete_task(task["task_id"], status=ScheduledTaskStatus.COMPLETED, duration_ms=1200)

    summary = build_daily_report_summary(report_date=date.today())
    assert summary["investigations_executed"] >= 1
    assert "success_rate_pct" in summary


def test_daily_report_store_and_idempotent(alert_db):
    with patch(
        "app.jarvis.investigations.alerting.daily_report.send_daily_health_report",
        return_value=True,
    ):
        first = generate_and_store_daily_report(report_date=date.today(), send_telegram=True)
        second = generate_and_store_daily_report(report_date=date.today(), send_telegram=False)
    assert first["report_date"] == second["report_date"]
    assert first["report_id"] == second["report_id"]


def test_maybe_generate_daily_report_respects_hour(monkeypatch, alert_db):
    monkeypatch.setenv("JARVIS_DAILY_REPORT_HOUR_UTC", "8")
    with patch("app.jarvis.investigations.alerting.daily_report._now_utc") as mock_now:
        mock_now.return_value = datetime(2026, 6, 16, 7, 0, tzinfo=timezone.utc)
        assert maybe_generate_daily_report() is None


# --- API endpoints ---


@pytest.fixture()
def jarvis_client():
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def test_api_list_alerts(jarvis_client, alert_db):
    alert_input = AlertInput(
        alert_type="test",
        source="api",
        title="Test alert",
        summary="Summary",
        severity=AlertSeverity.WARNING,
        normalized_finding="test api summary",
    )
    upsert_alert(alert_input, fingerprint=build_fingerprint(alert_input), suppression_window_hours=24)
    resp = jarvis_client.get("/api/jarvis/alerts")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["alerts"]) >= 1


def test_api_acknowledge_and_resolve(jarvis_client, alert_db):
    alert_input = AlertInput(
        alert_type="test",
        source="api",
        title="Ack test",
        summary="Summary",
        severity=AlertSeverity.WARNING,
        normalized_finding="ack test",
    )
    record = upsert_alert(alert_input, fingerprint=build_fingerprint(alert_input), suppression_window_hours=24)
    ack = jarvis_client.post(f"/api/jarvis/alerts/{record.alert_id}/acknowledge")
    assert ack.status_code == 200
    assert ack.json()["status"] == AlertStatus.ACKNOWLEDGED.value
    resolved = jarvis_client.post(f"/api/jarvis/alerts/{record.alert_id}/resolve")
    assert resolved.status_code == 200
    assert resolved.json()["status"] == AlertStatus.RESOLVED.value


def test_api_daily_reports(jarvis_client, alert_db):
    from app.jarvis.investigations.alerting.persistence import save_daily_report

    save_daily_report(report_date=date.today(), summary={"investigations_executed": 5})
    resp = jarvis_client.get("/api/jarvis/reports")
    assert resp.status_code == 200
    assert len(resp.json()["reports"]) >= 1


# --- Scheduler integration ---


def test_scheduler_emits_alert_on_execute(alert_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_ALERTING_ENABLED", "true")
    fake_report = type(
        "Report",
        (),
        {
            "investigation_id": "inv-sched-1",
            "status": type("S", (), {"value": "completed"})(),
            "summary": "All checks passed — healthy",
            "root_cause": None,
            "category": "database",
            "template_id": "generic",
            "objective": "Check database",
            "evidence": [],
            "impact": "",
            "collector_failures": [],
            "resolution_status": None,
        },
    )()
    with patch(
        "app.jarvis.investigations.scheduler.service.submit_investigation_readonly",
        return_value=fake_report,
    ):
        with patch(
            "app.jarvis.investigations.scheduler.service._maybe_emit_investigation_alert",
        ) as alert_mock:
            from app.jarvis.investigations.scheduler.service import execute_task

            execute_task(
                {
                    "task_id": "t1",
                    "schedule_id": "database_health",
                    "template_id": "generic",
                    "objective": "Check database",
                }
            )
            alert_mock.assert_called_once()


# --- Safety policy ---


def test_phase5_write_gates_remain_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_PATCH_APPLY_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_PR_CREATION_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_WRITE_ENABLED", raising=False)
    status = phase5_safety_status()
    assert status["patch_apply_enabled"] is False
    assert status["pr_creation_enabled"] is False
    assert status["github_write_enabled"] is False


def test_forbidden_objectives_still_blocked(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    objective = "Investigate and execute trade if missing orders are detected"
    assert classify_text(objective) == SafetyLevel.FORBIDDEN


def test_alerting_default_enabled(monkeypatch):
    monkeypatch.delenv("JARVIS_ALERTING_ENABLED", raising=False)
    assert alert_config.jarvis_alerting_enabled() is True


def test_suppression_window_default_24h(monkeypatch):
    monkeypatch.delenv("JARVIS_ALERT_SUPPRESSION_WINDOW_HOURS", raising=False)
    assert alert_config.jarvis_alert_suppression_window_hours() == 24


def test_ensure_tables(alert_db):
    assert ensure_tables() is True
    assert list_alerts(limit=1) == [] or isinstance(list_alerts(limit=1), list)
