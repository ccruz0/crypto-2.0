"""Reject FILLED/trade-history RC outside executed_orders_missing (morning 2026-08-10).

Scheduled database_health runs count_orders_by_status, which always shows FILLED>0
on a live book. That used to complete the probe with the trade-history canned cause
and page Telegram CRITICAL via loose category boost on \"query errors\".
"""

from __future__ import annotations

from app.jarvis.investigations.alerting.severity import classify_investigation_report
from app.jarvis.investigations.alerting.types import AlertSeverity
from app.jarvis.investigations.investigation_report import (
    _FILLED_TRADE_HISTORY_CAUSE,
    build_investigation_report,
    rank_root_causes,
    validate_investigation_report_fields,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus


_HEALTHY_DB_EVIDENCE = [
    {
        "source": "logs",
        "reference": "search_logs",
        "detail": (
            "No log matches for keywords=('postgres', 'database', 'sql', 'query') "
            "in services=['backend-aws']; match_count=0"
        ),
        "confidence": "low",
    },
    {
        "source": "runtime",
        "reference": "inspect_health",
        "detail": "Health check status=pass; global_status=PASS",
        "confidence": "high",
    },
    {
        "source": "runtime",
        "reference": "inspect_runtime",
        "detail": "environment=aws; jarvis_enabled=false; jarvis_dry_run_only=true",
        "confidence": "medium",
    },
    {
        "source": "database",
        "reference": "count_orders_by_status",
        "detail": "table=exchange_orders; status_counts: FILLED=1200, ACTIVE=4",
        "confidence": "high",
    },
]


class TestFilledTradeHistoryCauseScoped:
    def test_validate_rejects_filled_cause_on_database_health(self):
        status = validate_investigation_report_fields(
            root_cause=_FILLED_TRADE_HISTORY_CAUSE,
            evidence=_HEALTHY_DB_EVIDENCE,
            confidence=71.0,
            recommended_fix="Verify trade-history API route returns FILLED rows.",
            template_id="database_health",
            category="database",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_validate_allows_filled_cause_on_executed_orders_missing(self):
        status = validate_investigation_report_fields(
            root_cause=_FILLED_TRADE_HISTORY_CAUSE,
            evidence=_HEALTHY_DB_EVIDENCE
            + [
                {
                    "source": "dashboard",
                    "reference": "trade_history",
                    "detail": "executed orders missing from trade history UI",
                    "confidence": "high",
                }
            ],
            confidence=80.0,
            recommended_fix="Verify trade-history API route returns FILLED rows.",
            template_id="executed_orders_missing",
            category="orders",
        )
        assert status == InvestigationStatus.COMPLETED

    def test_database_health_pipeline_is_info_not_critical(self):
        ranked = rank_root_causes(
            evidence=_HEALTHY_DB_EVIDENCE,
            category="database",
            objective="Check database health and recent query errors",
            template_id="database_health",
        )
        assert any(c.cause == _FILLED_TRADE_HISTORY_CAUSE for c in ranked)

        report = build_investigation_report(
            investigation_id="inv-db-health-morning",
            objective="Check database health and recent query errors",
            category="database",
            template_id="database_health",
            evidence=_HEALTHY_DB_EVIDENCE,
            ranked_causes=ranked,
            created_at="2026-08-10T00:00:00+00:00",
        )
        assert report.status == InvestigationStatus.INSUFFICIENT_EVIDENCE

        alert = classify_investigation_report(report, source="database_health")
        assert alert is not None
        assert alert.severity == AlertSeverity.INFO
        assert alert.alert_type == "investigation_insufficient_evidence"
        assert alert.alert_type != "database_unavailable"
