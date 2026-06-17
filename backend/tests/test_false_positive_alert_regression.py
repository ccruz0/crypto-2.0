"""Regression tests for alert-b01932b9e17b false-positive CRITICAL on resolved open-order investigations."""

from __future__ import annotations

import pytest

from app.jarvis.investigations.alerting.severity import classify_investigation_report
from app.jarvis.investigations.alerting.types import AlertSeverity
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
