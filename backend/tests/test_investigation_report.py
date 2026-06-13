"""Tests for investigation report building and validation."""

from __future__ import annotations

from app.jarvis.investigations.evidence_model import EvidenceItem
from app.jarvis.investigations.investigation_report import (
    InvestigationReport,
    RootCauseCandidate,
    build_investigation_report,
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
