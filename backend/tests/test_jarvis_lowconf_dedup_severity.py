"""Follow-up to PR #85: stop recurring false-positive Jarvis Telegram alerts.

Covers two layers of the gap that PR #85 left open:

Part C (classification): a COMPLETED investigation with sub-threshold confidence
whose evidence is entirely healthy/PASS must classify as INFO (non-finding) and
must NOT be boosted to CRITICAL/WARNING via the category-boost path.

Part B (dedup severity + Telegram re-send gate): on a fingerprint dedup match the
freshly computed severity is re-applied to the existing row, and the engine does
not re-page Telegram for an unchanged or downgraded duplicate within the
suppression window — only new fingerprints or genuine escalations page.
"""

from __future__ import annotations

import pytest

from app.jarvis.investigations.alerting import config as alert_config
from app.jarvis.investigations.alerting import engine as alert_engine
from app.jarvis.investigations.alerting.engine import _emit_alert, _should_send_for_dedup
from app.jarvis.investigations.alerting.fingerprint import build_fingerprint
from app.jarvis.investigations.alerting.persistence import upsert_alert
from app.jarvis.investigations.alerting.severity import (
    _action_confidence_threshold,
    classify_investigation_report,
)
from app.jarvis.investigations.alerting.telegram import should_send_telegram
from app.jarvis.investigations.alerting.types import AlertInput, AlertRecord, AlertSeverity
from app.jarvis.investigations.investigation_types import InvestigationStatus


@pytest.fixture()
def alert_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    import app.database as db_mod
    from app.jarvis.investigations.alerting import persistence as alert_persist_mod

    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    db_mod.ensure_jarvis_alerting_tables(engine)
    monkeypatch.setattr(db_mod, "engine", engine)
    monkeypatch.setattr(alert_persist_mod, "engine", engine)
    yield engine
    engine.dispose()


_HEALTHY_EVIDENCE = [
    {
        "source": "runtime",
        "reference": "health_endpoint",
        "detail": "Health check status=pass",
        "confidence": "high",
    },
    {
        "source": "logs",
        "reference": "search_logs",
        "detail": "No log matches for keywords=['error'] in services=['backend']; match_count=0",
        "confidence": "low",
    },
]


def _fake_report(**kwargs):
    defaults = {
        "investigation_id": "inv-lowconf",
        "objective": "Check database health",
        "category": "database",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED,
        "summary": "Database health investigation\n- health=pass\n- error logs match_count=0",
        "evidence": list(_HEALTHY_EVIDENCE),
        "root_cause": "Deployment health check failing",
        "confidence": 42.0,
        "impact": "",
        "next_action": "",
        "collector_failures": [],
        "resolution_status": None,
    }
    defaults.update(kwargs)
    return type("Report", (), defaults)()


def _record_from(alert_input: AlertInput) -> AlertRecord:
    return AlertRecord(
        alert_id="a",
        created_at="2026-06-29T00:00:00Z",
        severity=alert_input.severity.value,
        source=alert_input.source,
        investigation_id=alert_input.investigation_id,
        title=alert_input.title,
        summary=alert_input.summary,
        evidence=alert_input.evidence,
        status="open",
        fingerprint="f",
        last_seen="2026-06-29T00:00:00Z",
    )


# --------------------------------------------------------------------------- #
# Part C: classification
# --------------------------------------------------------------------------- #


class TestLowConfidenceAllPassClassification:
    def test_threshold_defaults_to_seventy(self, monkeypatch):
        monkeypatch.delenv("JARVIS_SELF_HEALING_ACW_THRESHOLD", raising=False)
        assert _action_confidence_threshold() == 70.0

    def test_completed_lowconf_allpass_is_info_and_not_telegrammed(self):
        """The exact stale-alert shape: COMPLETED, ~42 confidence, all PASS evidence."""
        report = _fake_report()
        result = classify_investigation_report(report, source="database_health")
        assert result is not None
        assert result.severity == AlertSeverity.INFO
        assert result.alert_type == "investigation_low_confidence_all_pass"

        record = _record_from(result)
        assert should_send_telegram(record, info_enabled=False) is False
        assert should_send_telegram(record, info_enabled=True) is True

    def test_lowconf_allpass_not_boosted_to_critical_by_category(self):
        """TRAP: category=database + 'error' in objective/impact must NOT become CRITICAL.

        The low-confidence all-PASS gate is evaluated before _category_boost, so a
        healthy database investigation can never be escalated to database_unavailable.
        """
        report = _fake_report(
            objective="Investigate database error rates",
            impact="Elevated error counts observed in dashboard",
            root_cause="Database error investigation could not confirm a cause",
        )
        result = classify_investigation_report(report, source="database_health")
        assert result is not None
        assert result.severity == AlertSeverity.INFO
        assert result.alert_type != "database_unavailable"
        assert result.severity != AlertSeverity.CRITICAL

    def test_confidence_at_or_above_threshold_is_not_downgraded(self):
        """A confident healthy finding is not the target — it falls through unchanged."""
        report = _fake_report(confidence=85.0)
        result = classify_investigation_report(report, source="database_health")
        # High-confidence + only healthy evidence + meaningful root cause: not the
        # low-confidence gate; remains a (WARNING) finding so behaviour is unchanged.
        assert result is not None
        assert result.alert_type != "investigation_low_confidence_all_pass"

    def test_missing_confidence_does_not_trigger_downgrade(self):
        """Older callers without a confidence field must not be downgraded silently."""
        bare = type("Report", (), {
            "investigation_id": "inv-x",
            "objective": "Check database health",
            "category": "database",
            "template_id": "generic",
            "status": InvestigationStatus.COMPLETED,
            "summary": "Database health investigation\n- health=pass",
            "evidence": list(_HEALTHY_EVIDENCE),
            "root_cause": "Deployment health check failing",
            "impact": "",
            "next_action": "",
            "collector_failures": [],
            "resolution_status": None,
        })()
        result = classify_investigation_report(bare, source="database_health")
        assert result is not None
        assert result.alert_type != "investigation_low_confidence_all_pass"

    def test_genuine_critical_with_failing_evidence_still_pages(self):
        """Failing evidence (sync_status=failed_auth) keeps CRITICAL even at low confidence."""
        report = _fake_report(
            category="exchange",
            summary="Exchange unreachable — cannot reach exchange API",
            root_cause="Exchange connectivity failed",
            confidence=30.0,
            evidence=[
                {
                    "source": "authentication",
                    "reference": "sync_status",
                    "detail": "Exchange sync_status=failed_auth; error=credentials rejected",
                    "confidence": "high",
                }
            ],
        )
        result = classify_investigation_report(report, source="exchange_connectivity")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "exchange_unreachable"

        record = _record_from(result)
        assert should_send_telegram(record, info_enabled=False) is True


# --------------------------------------------------------------------------- #
# Part B: dedup severity re-apply + Telegram re-send gate
# --------------------------------------------------------------------------- #


def _input(severity: AlertSeverity, *, alert_type="api_degradation", source="database_health") -> AlertInput:
    return AlertInput(
        alert_type=alert_type,
        source=source,
        title="API degraded",
        summary="API degradation detected on database health probe",
        severity=severity,
        normalized_finding=f"{alert_type} {source} api degradation detected",
    )


class TestDedupSeverityReapply:
    def test_dedup_reapplies_downgraded_severity_on_existing_row(self, alert_db):
        warning = _input(AlertSeverity.WARNING)
        fp = build_fingerprint(warning)
        first = upsert_alert(warning, fingerprint=fp, suppression_window_hours=24)
        assert first.severity == AlertSeverity.WARNING.value
        assert first.deduplicated is False

        info = _input(AlertSeverity.INFO)
        assert build_fingerprint(info) == fp  # same fingerprint
        second = upsert_alert(info, fingerprint=fp, suppression_window_hours=24)
        assert second.alert_id == first.alert_id
        assert second.deduplicated is True
        assert second.previous_severity == AlertSeverity.WARNING.value
        # Severity is re-applied on the existing row (no longer frozen at WARNING).
        assert second.severity == AlertSeverity.INFO.value

    def test_should_send_gate_logic(self):
        new = _record_from(_input(AlertSeverity.WARNING))
        new.deduplicated = False
        assert _should_send_for_dedup(new) is True

        unchanged = _record_from(_input(AlertSeverity.WARNING))
        unchanged.deduplicated = True
        unchanged.previous_severity = AlertSeverity.WARNING.value
        assert _should_send_for_dedup(unchanged) is False

        downgraded = _record_from(_input(AlertSeverity.INFO))
        downgraded.deduplicated = True
        downgraded.previous_severity = AlertSeverity.WARNING.value
        assert _should_send_for_dedup(downgraded) is False

        escalated = _record_from(_input(AlertSeverity.CRITICAL))
        escalated.deduplicated = True
        escalated.previous_severity = AlertSeverity.WARNING.value
        assert _should_send_for_dedup(escalated) is True


class TestEngineReSendGate:
    @pytest.fixture(autouse=True)
    def _enable(self, monkeypatch):
        monkeypatch.setenv("JARVIS_ALERTING_ENABLED", "true")
        monkeypatch.setenv("JARVIS_ALERT_SUPPRESSION_WINDOW_HOURS", "24")

    def test_downgraded_warning_to_info_stops_paging(self, alert_db, monkeypatch):
        sent = []
        monkeypatch.setattr(
            alert_engine,
            "send_investigation_alert",
            lambda record, **kw: sent.append(record.severity) or True,
        )

        first = _emit_alert(_input(AlertSeverity.WARNING))
        assert first is not None and first.telegram_sent is True  # new fingerprint pages

        second = _emit_alert(_input(AlertSeverity.INFO))
        assert second is not None
        assert second.deduplicated is True
        assert second.severity == AlertSeverity.INFO.value
        assert second.telegram_sent is False  # downgrade not re-paged
        assert sent == [AlertSeverity.WARNING.value]  # only the first page happened

    def test_unchanged_warning_not_repaged_but_escalation_pages(self, alert_db, monkeypatch):
        sent = []
        monkeypatch.setattr(
            alert_engine,
            "send_investigation_alert",
            lambda record, **kw: sent.append(record.severity) or True,
        )

        first = _emit_alert(_input(AlertSeverity.WARNING))
        assert first.telegram_sent is True

        repeat = _emit_alert(_input(AlertSeverity.WARNING))
        assert repeat.deduplicated is True
        assert repeat.telegram_sent is False  # unchanged duplicate within window: no re-page

        escalated = _emit_alert(_input(AlertSeverity.CRITICAL))
        assert escalated.deduplicated is True
        assert escalated.previous_severity == AlertSeverity.WARNING.value
        assert escalated.telegram_sent is True  # genuine escalation pages

        assert sent == [AlertSeverity.WARNING.value, AlertSeverity.CRITICAL.value]
