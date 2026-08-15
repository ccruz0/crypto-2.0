"""Reject open_orders_empty CRITICAL when the book is not empty (morning 2026-08-15).

ATP Control https://t.me/ATP_control_bot/200234 — scheduled open_orders_empty paged
CRITICAL with Likely cause \"Trigger order API failure blocks cache updates\" while
evidence showed Open-status count=31 / ACTIVE=31.

Root cause: active count-mismatch left resolution_status=active (Telegram CRITICAL)
while ranked RC stayed on the historical empty-book / trigger-50001 canned cause.
"""

from __future__ import annotations

from app.jarvis.investigations.alerting.severity import classify_investigation_report
from app.jarvis.investigations.alerting.types import AlertSeverity
from app.jarvis.investigations.investigation_report import (
    _OPEN_ORDERS_NOT_EMPTY_CAUSE,
    RootCauseCandidate,
    build_investigation_report,
    open_status_count_from_evidence,
    validate_investigation_report_fields,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus


_NONEMPTY_EVIDENCE = [
    {
        "source": "database",
        "reference": "count_open_orders",
        "detail": (
            "Open-status count (NEW/ACTIVE/PARTIALLY_FILLED): 31; "
            "query=SELECT COUNT(*) AS count FROM exchange_orders WHERE status IN (...)"
        ),
        "confidence": "high",
    },
    {
        "source": "database",
        "reference": "count_orders_by_status",
        "detail": "Orders by status: {'CANCELLED': 1551, 'FILLED': 542, 'REJECTED': 158, 'ACTIVE': 31}",
        "confidence": "high",
    },
    {
        "source": "runtime",
        "reference": "diagnose_open_orders",
        "detail": (
            "Warning: Trigger-order API returned error_code=50001 (non-fatal; "
            "regular orders synced successfully): ERR_INTERNAL"
        ),
        "confidence": "medium",
    },
    {
        "source": "database",
        "reference": "open_positions",
        "detail": "Open position symbols: [{'symbol': 'DOT_USD', 'open_commitments': 26}]",
        "confidence": "medium",
    },
]

_ACTIVE_MISMATCH_TOOLS = [
    {
        "tool": "diagnose_open_orders",
        "ok": True,
        "root_cause": "Open order counts differ across exchange, database, and dashboard",
        "exchange_total_count": 40,
        "dashboard_effective_count": 31,
        "db_open_count": 31,
        "cache_raw_count": 31,
        "exchange_data_verified": True,
        "trigger_orders_error_code": 50001,
        "trigger_orders_error": "ERR_INTERNAL",
    },
    {
        "tool": "reconcile_crypto_com_open_orders",
        "ok": True,
        "counts": {
            "exchange_live": 40,
            "database_open": 31,
            "dashboard_cache": 31,
        },
        "root_cause": "Reconciliation found discrepancy(ies)",
        "sources": {
            "exchange": {
                "data_verified": True,
                "trigger_orders_error_code": 50001,
            }
        },
    },
]


class TestOpenStatusCountParsing:
    def test_parses_open_status_count_line(self):
        assert open_status_count_from_evidence(_NONEMPTY_EVIDENCE) == 31

    def test_parses_active_dict_when_count_line_missing(self):
        evidence = [
            {
                "source": "database",
                "reference": "status",
                "detail": "Orders by status: {'ACTIVE': 12, 'FILLED': 9}",
                "confidence": "high",
            }
        ]
        assert open_status_count_from_evidence(evidence) == 12


class TestEmptyBookCauseRejectedWhenNonEmpty:
    def test_validate_rejects_trigger_cache_cause_when_open_count_positive(self):
        status = validate_investigation_report_fields(
            root_cause="Trigger order API failure blocks cache updates",
            evidence=_NONEMPTY_EVIDENCE,
            confidence=80.0,
            recommended_fix="Allow regular open orders to update cache independently.",
            template_id="open_orders_empty",
            category="orders",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_validate_allows_not_empty_cause(self):
        status = validate_investigation_report_fields(
            root_cause=_OPEN_ORDERS_NOT_EMPTY_CAUSE,
            evidence=_NONEMPTY_EVIDENCE,
            confidence=92.0,
            recommended_fix="No empty-book repair needed.",
            template_id="open_orders_empty",
            category="orders",
        )
        assert status == InvestigationStatus.COMPLETED


class TestOpenOrdersEmptyPipelineNonFinding:
    def test_nonempty_probe_is_info_not_critical_telegram(self):
        ranked = [
            RootCauseCandidate(
                cause="Trigger order API failure blocks cache updates",
                score=80.0,
                supporting_evidence=["trigger 50001"],
                explanation="historical empty-book cause",
            )
        ]
        report = build_investigation_report(
            investigation_id="inv-open-orders-morning-200234",
            objective="Why are open orders empty?",
            category="orders",
            template_id="open_orders_empty",
            evidence=_NONEMPTY_EVIDENCE,
            ranked_causes=ranked,
            tool_outputs=_ACTIVE_MISMATCH_TOOLS,
            created_at="2026-08-14T18:15:47+00:00",
        )

        assert report.root_cause == _OPEN_ORDERS_NOT_EMPTY_CAUSE
        assert report.resolution_status == "resolved"
        assert report.status == InvestigationStatus.COMPLETED
        assert "non-finding" in (report.summary or "").lower()

        alert = classify_investigation_report(report, source="open_orders_empty")
        assert alert is not None
        assert alert.severity == AlertSeverity.INFO
        # Telegram only pages CRITICAL by default — INFO must not interrupt.
        assert alert.severity != AlertSeverity.CRITICAL

    def test_severity_defense_ignores_stale_active_when_count_positive(self):
        """Even a stale resolution_status=active must not CRITICAL-page when not empty."""
        report = type(
            "Report",
            (),
            {
                "investigation_id": "inv-stale-active",
                "objective": "Why are open orders empty?",
                "category": "orders",
                "template_id": "open_orders_empty",
                "status": InvestigationStatus.COMPLETED,
                "summary": "Why are open orders empty?\nLikely cause: Trigger order API failure blocks cache updates",
                "evidence": _NONEMPTY_EVIDENCE,
                "root_cause": "Trigger order API failure blocks cache updates",
                "impact": "Dashboard shows empty open orders despite DB rows.",
                "next_action": "fix cache",
                "collector_failures": [],
                "resolution_status": "active",
                "confidence": 80.0,
            },
        )()
        alert = classify_investigation_report(report, source="open_orders_empty")
        assert alert is not None
        assert alert.severity != AlertSeverity.CRITICAL
