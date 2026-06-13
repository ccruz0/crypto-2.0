"""Tests for Jarvis Phase 4B proposal eligibility."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, text

from app.database import ensure_jarvis_investigations_table
from app.jarvis.investigations.investigation_report import InvestigationReport
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.investigations.persistence import (
    get_investigation,
    save_investigation,
    update_investigation_proposal_linkage,
)
from app.jarvis.proposals.eligibility import (
    ProposalEligibilityConfig,
    check_proposal_eligibility,
)

TRIGGER_ROOT_CAUSE = "Trigger order API failure blocks cache updates"
TRIGGER_RECOMMENDED_FIX = (
    "Allow regular open orders to update cache independently when trigger-order sync fails."
)


def _eligible_investigation(**overrides) -> dict:
    base = {
        "investigation_id": "inv-eligible-1",
        "objective": "Why does dashboard show zero open orders?",
        "category": "orders",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED.value,
        "summary": "Trigger order sync failure blocks cache refresh.",
        "root_cause": TRIGGER_ROOT_CAUSE,
        "confidence": 75.0,
        "evidence": [],
        "recommended_fix": TRIGGER_RECOMMENDED_FIX,
        "impact": "Dashboard shows zero open orders while exchange has active regular orders.",
        "ranked_causes": [],
        "verification_steps": [],
        "next_action": "Propose patch behind approval gate.",
        "proposal_task_id": None,
        "proposal_status": None,
        "created_at": "2026-06-13T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _enabled_config(**overrides) -> ProposalEligibilityConfig:
    values = {"proposals_enabled": True, "min_confidence": 50.0}
    values.update(overrides)
    return ProposalEligibilityConfig(**values)


@pytest.fixture()
def inv_db(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    ensure_jarvis_investigations_table(engine)
    monkeypatch.setattr("app.jarvis.investigations.persistence.engine", engine)
    monkeypatch.setattr("app.database.engine", engine)
    return engine


def _persist_report(report: InvestigationReport) -> None:
    assert save_investigation(report) is True


def _sample_report(**overrides) -> InvestigationReport:
    values = {
        "investigation_id": "inv-db-1",
        "objective": "Why does dashboard show zero open orders?",
        "category": "orders",
        "template_id": "generic",
        "status": InvestigationStatus.COMPLETED,
        "summary": "Trigger order sync failure.",
        "evidence": [],
        "root_cause": TRIGGER_ROOT_CAUSE,
        "confidence": 75.0,
        "ranked_causes": [],
        "impact": "Dashboard mismatch.",
        "recommended_fix": TRIGGER_RECOMMENDED_FIX,
        "verification_steps": ["Re-run reconcile_crypto_com_open_orders after fix deployment."],
        "next_action": "Propose patch.",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    values.update(overrides)
    return InvestigationReport(**values)


class TestProposalEligibility:
    def test_eligible_when_flag_enabled_and_investigation_complete(self):
        result = check_proposal_eligibility(
            _eligible_investigation(),
            config=_enabled_config(),
        )
        assert result.eligible is True
        assert result.reasons == []
        assert result.confidence == 75.0
        assert len(result.fix_template_candidates) == 1
        assert result.fix_template_candidates[0]["fix_template_id"] == (
            "orders.trigger_50001_cache_independent"
        )

    def test_not_eligible_when_flag_disabled(self, monkeypatch):
        monkeypatch.delenv("JARVIS_4B_PROPOSALS_ENABLED", raising=False)
        result = check_proposal_eligibility(_eligible_investigation())
        assert result.eligible is False
        assert "phase4b_proposals_disabled" in result.reasons

    def test_flag_disabled_reason_skipped_with_include_disabled_reason(self, monkeypatch):
        monkeypatch.delenv("JARVIS_4B_PROPOSALS_ENABLED", raising=False)
        result = check_proposal_eligibility(
            _eligible_investigation(),
            config=_enabled_config(),
            include_disabled_reason=True,
        )
        assert result.eligible is True
        assert "phase4b_proposals_disabled" not in result.reasons

    def test_insufficient_evidence_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(status=InvestigationStatus.INSUFFICIENT_EVIDENCE.value),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "investigation_not_completed" in result.reasons

    def test_missing_root_cause_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(root_cause=""),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "missing_root_cause" in result.reasons
        assert result.fix_template_candidates == []

    def test_missing_recommended_fix_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(recommended_fix=""),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "missing_recommended_fix" in result.reasons

    def test_confidence_below_threshold_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(confidence=40.0),
            config=_enabled_config(min_confidence=50.0),
        )
        assert result.eligible is False
        assert "confidence_below_threshold" in result.reasons

    def test_active_proposal_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(
                proposal_task_id="task-abc",
                proposal_status="waiting_for_approval",
            ),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "active_proposal_exists" in result.reasons
        assert result.existing_proposal_task_id == "task-abc"

    def test_unknown_root_cause_no_fix_template_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(root_cause="Unknown exotic production failure"),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "no_fix_template" in result.reasons
        assert result.fix_template_candidates == []

    def test_forbidden_recommended_fix_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(recommended_fix="Deploy to production immediately"),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "forbidden_recommended_fix" in result.reasons

    def test_forbidden_objective_not_eligible(self):
        result = check_proposal_eligibility(
            _eligible_investigation(objective="Execute order on BTC-USD"),
            config=_enabled_config(),
        )
        assert result.eligible is False
        assert "forbidden_objective" in result.reasons

    def test_persistence_exposes_proposal_fields(self, inv_db):
        _persist_report(_sample_report(investigation_id="inv-proposal-fields"))
        update_investigation_proposal_linkage(
            "inv-proposal-fields",
            proposal_task_id="task-123",
            proposal_status="waiting_for_approval",
        )
        row = get_investigation("inv-proposal-fields")
        assert row is not None
        assert row["proposal_task_id"] == "task-123"
        assert row["proposal_status"] == "waiting_for_approval"

    def test_save_investigation_preserves_proposal_linkage(self, inv_db):
        inv_id = "inv-preserve-link"
        _persist_report(_sample_report(investigation_id=inv_id))
        update_investigation_proposal_linkage(
            inv_id,
            proposal_task_id="task-preserve",
            proposal_status="proposing",
        )
        _persist_report(
            _sample_report(
                investigation_id=inv_id,
                summary="Updated summary after re-run.",
            )
        )
        row = get_investigation(inv_id)
        assert row is not None
        assert row["proposal_task_id"] == "task-preserve"
        assert row["proposal_status"] == "proposing"
        assert row["summary"] == "Updated summary after re-run."

    def test_boot_hook_adds_proposal_columns(self, inv_db):
        with inv_db.connect() as conn:
            cols = {
                row[1]
                for row in conn.execute(text("PRAGMA table_info(jarvis_investigations)")).fetchall()
            }
        assert "proposal_task_id" in cols
        assert "proposal_status" in cols
