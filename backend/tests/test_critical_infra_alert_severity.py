"""OPTION 2: CRITICAL severity for exchange/database infrastructure outages."""

from __future__ import annotations

import pytest

from app.jarvis.investigations.alerting.severity import (
    _is_active_open_order_mismatch,
    _is_resolved_healthy,
    classify_investigation_report,
)
from app.jarvis.investigations.alerting.types import AlertSeverity
from app.jarvis.investigations.investigation_report import (
    build_investigation_report,
    rank_root_causes,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus


def _fake_report(**kwargs):
    defaults = {
        "investigation_id": "inv-infra-test",
        "objective": "Infrastructure health check",
        "category": "exchange",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED,
        "summary": "",
        "evidence": [],
        "root_cause": None,
        "impact": "",
        "next_action": "",
        "collector_failures": [],
        "resolution_status": None,
    }
    defaults.update(kwargs)
    return type("Report", (), defaults)()


def _resolved_mismatch_tool_outputs(
    *,
    exchange: int = 5,
    dashboard: int = 5,
    db: int = 2,
) -> list[dict]:
    return [
        {
            "tool": "diagnose_open_orders",
            "ok": True,
            "root_cause": "Open order counts differ across exchange, database, and dashboard",
            "exchange_total_count": exchange,
            "dashboard_effective_count": dashboard,
            "db_open_count": db,
            "cache_raw_count": exchange,
            "exchange_data_verified": True,
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
            "sources": {"exchange": {"data_verified": True}},
        },
    ]


class TestExchangeInfrastructureCritical:
    @pytest.mark.parametrize(
        "summary,root_cause",
        [
            ("Exchange unreachable — cannot reach exchange API", "Exchange connectivity failed"),
            ("Exchange unavailable for trading operations", "Exchange API unavailable"),
            ("Scheduled exchange health check failed", "Exchange request failed after retries"),
        ],
    )
    def test_exchange_outage_classifies_critical(self, summary, root_cause):
        report = _fake_report(
            category="exchange",
            summary=summary,
            root_cause=root_cause,
        )
        result = classify_investigation_report(report, source="exchange_connectivity")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "exchange_unreachable"

    def test_exchange_auth_failure_preventing_operation_is_critical(self):
        report = _fake_report(
            category="authentication",
            summary="Exchange authentication failure preventing operation",
            root_cause="Exchange authentication failed — credentials rejected",
        )
        result = classify_investigation_report(report, source="exchange_connectivity")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "exchange_unreachable"


class TestDatabaseInfrastructureCritical:
    @pytest.mark.parametrize(
        "summary,root_cause",
        [
            ("Database unavailable", "Database unavailable"),
            ("Primary database is down", "Database down — connection pool exhausted"),
            ("Health check failed", "Database connection failed"),
        ],
    )
    def test_database_outage_classifies_critical(self, summary, root_cause):
        report = _fake_report(
            category="database",
            summary=summary,
            root_cause=root_cause,
        )
        result = classify_investigation_report(report, source="database_health")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "database_unavailable"

    def test_cannot_connect_to_database_without_category_boost(self):
        """Non-database category still escalates via _CRITICAL_INFRA_RULES on authoritative text."""
        report = _fake_report(
            category="api",
            summary="Cannot connect to database during API health probe",
            root_cause="Database connection failed",
        )
        result = classify_investigation_report(report, source="api_health")
        assert result is not None
        assert result.severity == AlertSeverity.CRITICAL
        assert result.alert_type == "database_unavailable"


class TestB01932RegressionStillInfo:
    def test_resolved_open_order_mismatch_stays_info(self):
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=5, db=2)
        evidence = [
            {
                "source": "exchange",
                "reference": "reconciliation_counts",
                "detail": "Exchange=5, DB=2, dashboard=5",
                "confidence": "high",
            }
        ]
        ranked = rank_root_causes(evidence=evidence, category="dashboard", tool_outputs=tool_outputs)
        report = build_investigation_report(
            investigation_id="inv-b01932-option2",
            objective="Why are my open orders different from Crypto.com?",
            category="dashboard",
            template_id="dashboard_exchange_mismatch",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=tool_outputs,
            created_at="2026-06-17T00:00:00+00:00",
        )
        assert report.resolution_status == "resolved"
        assert report.root_cause == "No active dashboard/exchange mismatch detected"

        result = classify_investigation_report(report, source="dashboard_exchange_mismatch")
        assert result is not None
        assert result.severity == AlertSeverity.INFO
        assert result.alert_type == "investigation_completed"


class TestActiveMismatchStillCritical:
    def test_exchange5_dashboard0_stays_critical(self):
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=0, db=2)
        evidence = [
            {
                "source": "exchange",
                "reference": "reconciliation_counts",
                "detail": "Exchange=5, DB=2, dashboard=0",
                "confidence": "high",
            }
        ]
        ranked = rank_root_causes(evidence=evidence, category="dashboard", tool_outputs=tool_outputs)
        report = build_investigation_report(
            investigation_id="inv-active-mismatch",
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


class TestNonInfraWarningUnchanged:
    def test_missing_production_data_remains_warning(self):
        report = _fake_report(
            category="api",
            summary="Missing production data for reconciliation",
            root_cause="No production data in orders table",
            impact="Cannot reconcile",
        )
        result = classify_investigation_report(report, source="api_health")
        assert result is not None
        assert result.severity == AlertSeverity.WARNING
        assert result.alert_type == "missing_production_data"

    def test_repeated_investigation_failures_remain_warning(self):
        report = _fake_report(
            category="api",
            objective="Review scheduler reliability",
            summary="Repeated investigation failures detected",
            root_cause="Scheduler failures over 24h",
        )
        result = classify_investigation_report(report, source="scheduler")
        assert result is not None
        assert result.severity == AlertSeverity.WARNING
        assert result.alert_type == "repeated_investigation_failures"


class TestLatentSubstringMismatchBug:
    """Document latent false-positive risk in _is_active_open_order_mismatch (not fixed here)."""

    def test_resolved_root_cause_matches_active_mismatch_substring(self):
        report = _fake_report(
            root_cause="No active dashboard/exchange mismatch detected",
            resolution_status="resolved",
        )
        assert _is_resolved_healthy(report) is True
        # Masked today: substring rule matches before tree exits via step 3.
        assert _is_active_open_order_mismatch(report) is True

    def test_without_resolved_status_substring_would_be_reachable(self):
        report = _fake_report(
            root_cause="No active dashboard/exchange mismatch detected",
            resolution_status=None,
        )
        assert _is_resolved_healthy(report) is True  # root_cause exact match
        assert _is_active_open_order_mismatch(report) is True
