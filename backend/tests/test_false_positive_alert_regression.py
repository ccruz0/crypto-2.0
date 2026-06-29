"""Regression tests for alert-b01932b9e17b false-positive CRITICAL on resolved open-order investigations."""

from __future__ import annotations

import pytest

from app.jarvis.investigations.alerting.severity import classify_investigation_report
from app.jarvis.investigations.alerting.telegram import should_send_telegram
from app.jarvis.investigations.alerting.types import AlertRecord, AlertSeverity
from app.jarvis.investigations.investigation_report import (
    build_investigation_report,
    classify_open_orders_mismatch,
    rank_root_causes,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.models.exchange_order import OrderStatusEnum
from app.services.exchange_sync import map_exchange_order_status


def _resolved_mismatch_tool_outputs(
    *,
    exchange: int = 5,
    dashboard: int = 5,
    db: int = 2,
    cache: int = 5,
    trigger_code: int | None = 50001,
) -> list[dict]:
    return [
        {
            "tool": "diagnose_open_orders",
            "ok": True,
            "root_cause": "Open order counts differ across exchange, database, and dashboard",
            "exchange_total_count": exchange,
            "dashboard_effective_count": dashboard,
            "db_open_count": db,
            "cache_raw_count": cache,
            "exchange_data_verified": True,
            "trigger_orders_error_code": trigger_code,
            "trigger_orders_error": "ERR_INTERNAL" if trigger_code else None,
        },
        {
            "tool": "reconcile_crypto_com_open_orders",
            "ok": True,
            "counts": {
                "exchange_live": exchange,
                "database_open": db,
                "dashboard_cache": dashboard,
            },
            "root_cause": "Reconciliation found 6 discrepancy(ies)",
            "sources": {
                "exchange": {
                    "data_verified": True,
                    "trigger_orders_error_code": trigger_code,
                }
            },
        },
    ]


def _fake_report(**kwargs):
    defaults = {
        "investigation_id": "inv-fp-regression",
        "objective": "Why are my open orders different from Crypto.com?",
        "category": "dashboard",
        "template_id": "dashboard_exchange_mismatch",
        "status": InvestigationStatus.COMPLETED,
        "summary": "",
        "evidence": [],
        "root_cause": None,
        "impact": "",
        "collector_failures": [],
        "resolution_status": None,
    }
    defaults.update(kwargs)
    return type("Report", (), defaults)()


class TestPhase1CountVerification:
    """Document why Exchange=5, Dashboard=5, DB=2 is expected before PENDING mapping fix."""

    def test_pending_maps_to_active_so_db_can_count_trigger_orders(self):
        assert map_exchange_order_status("PENDING") == OrderStatusEnum.ACTIVE

    def test_unknown_status_excluded_from_db_open_count(self):
        """DB open queries use NEW/ACTIVE/PARTIALLY_FILLED only — UNKNOWN rows are excluded."""
        open_statuses = {
            OrderStatusEnum.NEW,
            OrderStatusEnum.ACTIVE,
            OrderStatusEnum.PARTIALLY_FILLED,
        }
        assert OrderStatusEnum.UNKNOWN not in open_statuses
        assert map_exchange_order_status("PENDING") in open_statuses

    def test_exchange_dashboard_match_db_diff_is_resolved_not_active(self):
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=5, db=2, cache=5)
        classification = classify_open_orders_mismatch(tool_outputs)
        assert classification is not None
        assert classification.active_mismatch is False
        assert classification.resolution == "resolved"
        assert classification.root_cause == "No active dashboard/exchange mismatch detected"
        assert any("DB stores regular open-status rows" in note for note in classification.notes)


class TestFalsePositiveAlertRegression:
    """Phase 5 regression cases for alert severity."""

    def test_case1_exchange5_dashboard5_db2_no_critical(self):
        """Exchange=5 Dashboard=5 DB=2 with resolved investigation must not emit CRITICAL."""
        tool_outputs = _resolved_mismatch_tool_outputs()
        evidence = [
            {
                "source": "exchange",
                "reference": "reconciliation_counts",
                "detail": "Exchange=5, DB=2, dashboard=5",
                "confidence": "high",
            },
            {
                "source": "exchange",
                "reference": "trigger_orders_api",
                "detail": "Trigger-order API error_code=50001: ERR_INTERNAL",
                "confidence": "high",
            },
        ]
        ranked = rank_root_causes(evidence=evidence, category="dashboard", tool_outputs=tool_outputs)
        report = build_investigation_report(
            investigation_id="inv-case1",
            objective="Why are my open orders different from Crypto.com?",
            category="dashboard",
            template_id="dashboard_exchange_mismatch",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=tool_outputs,
            created_at="2026-06-17T00:00:00+00:00",
        )
        assert report.root_cause == "No active dashboard/exchange mismatch detected"
        assert report.resolution_status == "resolved"

        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity != AlertSeverity.CRITICAL
        assert result.severity == AlertSeverity.INFO

    def test_case2_exchange5_dashboard0_critical(self):
        """True dashboard/exchange mismatch must remain CRITICAL."""
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=0, db=2, cache=0)
        evidence = [
            {
                "source": "exchange",
                "reference": "reconciliation_counts",
                "detail": "Exchange=5, DB=2, dashboard=0",
                "confidence": "high",
            }
        ]
        ranked = rank_root_causes(
            evidence=evidence,
            category="dashboard",
            tool_outputs=tool_outputs,
        )
        report = build_investigation_report(
            investigation_id="inv-case2",
            objective="Why are my open orders different from Crypto.com?",
            category="dashboard",
            template_id="dashboard_exchange_mismatch",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=tool_outputs,
            created_at="2026-06-17T00:00:00+00:00",
        )
        assert report.resolution_status == "active"

        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "open_order_inconsistency"

    def test_case3_resolved_healthy_info_or_suppressed(self):
        report = _fake_report(
            summary="Conclusion: No active dashboard/exchange mismatch detected",
            root_cause="No active dashboard/exchange mismatch detected",
            resolution_status="resolved",
            evidence=[
                {
                    "source": "exchange",
                    "detail": "Open order counts differ across exchange, database, and dashboard",
                    "reference": "diagnose_open_orders",
                }
            ],
        )
        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity == AlertSeverity.INFO

    def test_case4_exchange_unreachable_critical(self):
        report = _fake_report(
            category="exchange",
            summary="Exchange unreachable — cannot reach exchange API",
            root_cause="Exchange connectivity failed",
            status=InvestigationStatus.COMPLETED,
        )
        result = classify_investigation_report(report, source="exchange_connectivity")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "exchange_unreachable"

    def test_case5_investigation_incomplete_warning(self):
        report = _fake_report(
            status=InvestigationStatus.PARTIAL_FAILURE,
            summary="Collector could not reach all data sources",
            root_cause="Insufficient evidence from trigger-order API",
        )
        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity == AlertSeverity.WARNING
        assert result.alert_type == "investigation_partial_failure"

    def test_case5b_partial_failure_still_warning_telegram(self):
        """A genuine partial collector failure must remain WARNING and still page."""
        report = _fake_report(
            status=InvestigationStatus.PARTIAL_FAILURE,
            summary="Collector could not reach all data sources",
            root_cause="Insufficient evidence from trigger-order API",
        )
        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity == AlertSeverity.WARNING
        assert result.alert_type == "investigation_partial_failure"

    def test_intermediate_diagnostic_text_does_not_override_resolved_conclusion(self):
        """Evidence with 'open order counts differ' must not escalate when conclusion is healthy."""
        report = _fake_report(
            summary=(
                "Why are my open orders different from Crypto.com?\n"
                "- Exchange=5, DB=2, dashboard=5\n"
                "Conclusion: No active dashboard/exchange mismatch detected"
            ),
            root_cause="No active dashboard/exchange mismatch detected",
            resolution_status="resolved",
            evidence=[
                {
                    "source": "exchange",
                    "detail": "Open order counts differ across exchange, database, and dashboard",
                    "reference": "diagnose_open_orders",
                }
            ],
        )
        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity == AlertSeverity.INFO


def _alert_record_from(alert_input) -> AlertRecord:
    """Minimal AlertRecord built from a classifier AlertInput for send-gating checks."""
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


class TestInsufficientEvidenceNoTelegram:
    """Recurring scheduled investigations that end INSUFFICIENT_EVIDENCE must not page Telegram.

    These are the false-positive WARNINGs the operator kept receiving
    (deployment_unhealthy, portfolio_reconciliation_mismatch, jarvis_task_failing)
    where evidence was PASS but Jarvis fell back to a low-confidence canned cause.
    """

    @pytest.mark.parametrize(
        ("source", "category", "summary", "root_cause"),
        [
            (
                "deployment_unhealthy",
                "deployment",
                "Why is deployment unhealthy?\n- health=pass\n- GITHUB_APP_CUTOVER_HEALTH=PASS",
                "Deployment health check failing",
            ),
            (
                "portfolio_reconciliation_mismatch",
                "portfolio",
                "Investigate portfolio reconciliation mismatch\n- health=pass",
                "Portfolio equity derived from balances because exchange API omits equity field",
            ),
            (
                "jarvis_task_failing",
                "api",
                "Why is Jarvis task failing?\n- health=pass",
                "FILLED orders exist in database but dashboard trade history does not display them",
            ),
        ],
    )
    def test_insufficient_evidence_classified_info_and_not_sent(
        self, source, category, summary, root_cause
    ):
        report = _fake_report(
            category=category,
            template_id=source,
            status=InvestigationStatus.INSUFFICIENT_EVIDENCE,
            summary=summary,
            root_cause=root_cause,
        )
        result = classify_investigation_report(report, source=source)
        assert result is not None
        assert result.severity == AlertSeverity.INFO
        assert result.alert_type == "investigation_insufficient_evidence"
        # INFO alerts are not pushed to Telegram unless explicitly enabled.
        record = _alert_record_from(result)
        assert should_send_telegram(record, info_enabled=False) is False
        assert should_send_telegram(record, info_enabled=True) is True

    def test_insufficient_evidence_does_not_escalate_via_canned_warning_pattern(self):
        """Even when the canned cause text matches a WARNING regex, status wins → INFO."""
        report = _fake_report(
            category="deployment",
            template_id="deployment_unhealthy",
            status=InvestigationStatus.INSUFFICIENT_EVIDENCE,
            summary="Why is deployment unhealthy? Likely cause: deployment unhealthy / health check failing",
            root_cause="Deployment health check failing",
        )
        result = classify_investigation_report(report, source="deployment_unhealthy")
        assert result is not None
        assert result.severity == AlertSeverity.INFO
