"""Tests for investigation report building and validation."""

from __future__ import annotations

from app.jarvis.investigations.evidence_model import EvidenceItem
from app.jarvis.investigations.investigation_report import (
    InvestigationReport,
    RootCauseCandidate,
    build_investigation_report,
    classify_open_orders_mismatch,
    rank_root_causes,
    validate_investigation_report,
    validate_investigation_report_fields,
)
from app.jarvis.investigations.investigation_types import InvestigationStatus


def _sample_evidence() -> list[EvidenceItem]:
    return [
        {
            "source": "database",
            "reference": "exchange_orders",
            "detail": "Open-status count: 0",
            "confidence": "high",
        },
        {
            "source": "exchange",
            "reference": "reconciliation_counts",
            "detail": "Exchange=1, DB=1, dashboard=0",
            "confidence": "high",
        },
        {
            "source": "exchange",
            "reference": "trigger_orders_api",
            "detail": "Trigger-order API error_code=50001: Invalid request",
            "confidence": "high",
        },
    ]


class TestInvestigationReport:
    def test_completed_when_all_fields_present(self):
        ranked = [
            RootCauseCandidate(
                cause="Trigger order API failure blocks cache updates",
                score=92.0,
                supporting_evidence=["trigger 50001"],
                explanation="High confidence match.",
            )
        ]
        report = build_investigation_report(
            investigation_id="inv-1",
            objective="Why does dashboard differ from exchange?",
            category="dashboard",
            template_id="dashboard_exchange_mismatch",
            evidence=_sample_evidence(),
            ranked_causes=ranked,
            created_at="2026-06-13T00:00:00+00:00",
        )
        assert report.status == InvestigationStatus.COMPLETED
        assert report.root_cause
        assert report.confidence >= 25
        assert report.recommended_fix
        assert report.verification_steps

    def test_insufficient_evidence_without_root_cause(self):
        status = validate_investigation_report_fields(
            root_cause=None,
            evidence=_sample_evidence(),
            confidence=0,
            recommended_fix="",
        )
        assert status == InvestigationStatus.INSUFFICIENT_EVIDENCE

    def test_report_to_dict_includes_mandatory_sections(self):
        ranked = [
            RootCauseCandidate(cause="Test cause", score=80.0, explanation="test"),
        ]
        report = build_investigation_report(
            investigation_id="inv-2",
            objective="Test objective",
            category="orders",
            template_id="open_orders_empty",
            evidence=_sample_evidence(),
            ranked_causes=ranked,
            created_at="2026-06-13T00:00:00+00:00",
        )
        data = report.to_dict()
        for key in (
            "summary",
            "evidence",
            "root_cause",
            "confidence",
            "impact",
            "recommended_fix",
            "verification_steps",
            "next_action",
            "ranked_causes",
        ):
            assert key in data

    def test_validate_investigation_report_helper(self):
        report = InvestigationReport(
            investigation_id="x",
            objective="obj",
            category="orders",
            template_id="t",
            status=InvestigationStatus.COMPLETED,
            summary="s",
            evidence=_sample_evidence(),
            root_cause="cause",
            confidence=90.0,
            ranked_causes=[],
            impact="impact",
            recommended_fix="fix",
            verification_steps=["step"],
            next_action="next",
            created_at="2026-06-13T00:00:00+00:00",
        )
        assert validate_investigation_report(report) == InvestigationStatus.COMPLETED


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


class TestOpenOrdersMismatchClassification:
    def test_exchange_matches_dashboard_with_trigger_50001_is_resolved(self):
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
        assert ranked[0].cause == "No active dashboard/exchange mismatch detected"
        assert not any("blocks cache" in c.cause.lower() for c in ranked)

        classification = classify_open_orders_mismatch(tool_outputs)
        assert classification is not None
        assert classification.resolution == "resolved"
        assert classification.trigger_warning is not None
        assert "50001" in classification.trigger_warning

        report = build_investigation_report(
            investigation_id="inv-resolved",
            objective="Why are my open orders different from Crypto.com?",
            category="dashboard",
            template_id="dashboard_exchange_mismatch",
            evidence=evidence,
            ranked_causes=ranked,
            tool_outputs=tool_outputs,
            created_at="2026-06-14T00:00:00+00:00",
        )
        assert report.status == InvestigationStatus.COMPLETED
        assert report.root_cause == "No active dashboard/exchange mismatch detected"
        assert report.resolution_status == "resolved"
        assert "50001" in report.summary
        assert "DB stores regular open-status rows" in report.summary

    def test_exchange_dashboard_mismatch_is_active(self):
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=0, db=2, cache=0)
        classification = classify_open_orders_mismatch(tool_outputs)
        assert classification is not None
        assert classification.active_mismatch is True
        assert classification.resolution == "active"

        ranked = rank_root_causes(
            evidence=[
                {
                    "source": "exchange",
                    "reference": "reconciliation_counts",
                    "detail": "Exchange=5, DB=2, dashboard=0",
                    "confidence": "high",
                }
            ],
            category="dashboard",
            tool_outputs=tool_outputs,
        )
        assert ranked[0].cause != "No active dashboard/exchange mismatch detected"

    def test_exchange_dashboard_match_db_diff_is_data_model_note_not_incident(self):
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=5, db=2, cache=5)
        classification = classify_open_orders_mismatch(tool_outputs)
        assert classification is not None
        assert classification.active_mismatch is False
        assert any("DB stores regular open-status rows" in note for note in classification.notes)

    def test_stale_cache_with_dashboard_below_exchange_is_active_mismatch(self):
        tool_outputs = _resolved_mismatch_tool_outputs(exchange=5, dashboard=2, db=2, cache=2)
        classification = classify_open_orders_mismatch(tool_outputs)
        assert classification is not None
        assert classification.active_mismatch is True

        ranked = rank_root_causes(
            evidence=[
                {
                    "source": "exchange",
                    "reference": "reconciliation_counts",
                    "detail": "Exchange=5, DB=2, dashboard=2",
                    "confidence": "high",
                }
            ],
            category="dashboard",
            tool_outputs=tool_outputs,
        )
        assert ranked[0].cause != "No active dashboard/exchange mismatch detected"
