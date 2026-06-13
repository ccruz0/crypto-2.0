"""Proposal eligibility checks for Jarvis Phase 4B."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jarvis.execution.safety import SafetyLevel, classify_change_objective, is_forbidden
from app.jarvis.investigations.investigation_types import InvestigationStatus
from app.jarvis.proposals.config import jarvis_4b_min_confidence, jarvis_4b_proposals_enabled
from app.jarvis.proposals.fix_templates import find_fix_templates_for_root_cause

ACTIVE_PROPOSAL_STATUSES: frozenset[str] = frozenset(
    {
        "proposing",
        "waiting_for_approval",
        "approved",
    }
)


@dataclass
class ProposalEligibilityConfig:
    proposals_enabled: bool = False
    min_confidence: float = 50.0


@dataclass
class ProposalEligibilityResult:
    eligible: bool
    reasons: list[str] = field(default_factory=list)
    confidence: float = 0.0
    fix_template_candidates: list[dict[str, Any]] = field(default_factory=list)
    existing_proposal_task_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "eligible": self.eligible,
            "reasons": list(self.reasons),
            "confidence": self.confidence,
            "fix_template_candidates": list(self.fix_template_candidates),
            "existing_proposal_task_id": self.existing_proposal_task_id,
        }


def default_eligibility_config() -> ProposalEligibilityConfig:
    return ProposalEligibilityConfig(
        proposals_enabled=jarvis_4b_proposals_enabled(),
        min_confidence=jarvis_4b_min_confidence(),
    )


def _has_active_proposal(proposal_task_id: str | None, proposal_status: str | None) -> bool:
    task_id = (proposal_task_id or "").strip()
    if not task_id:
        return False
    status = (proposal_status or "").strip().lower()
    if not status or status == "none":
        return True
    return status in ACTIVE_PROPOSAL_STATUSES


def check_proposal_eligibility(
    investigation: dict[str, Any],
    config: ProposalEligibilityConfig | None = None,
    *,
    include_disabled_reason: bool = False,
) -> ProposalEligibilityResult:
    """Evaluate whether an investigation may enter the Phase 4B patch proposal workflow."""
    cfg = config or default_eligibility_config()
    reasons: list[str] = []

    confidence = float(investigation.get("confidence") or 0)
    existing_proposal_task_id = investigation.get("proposal_task_id")
    if existing_proposal_task_id is not None:
        existing_proposal_task_id = str(existing_proposal_task_id).strip() or None

    if not cfg.proposals_enabled and not include_disabled_reason:
        reasons.append("phase4b_proposals_disabled")

    status = (investigation.get("status") or "").strip()
    if status != InvestigationStatus.COMPLETED.value:
        reasons.append("investigation_not_completed")

    root_cause = (investigation.get("root_cause") or "").strip()
    if not root_cause:
        reasons.append("missing_root_cause")

    recommended_fix = (investigation.get("recommended_fix") or "").strip()
    if not recommended_fix:
        reasons.append("missing_recommended_fix")

    if confidence < cfg.min_confidence:
        reasons.append("confidence_below_threshold")

    proposal_status = investigation.get("proposal_status")
    if _has_active_proposal(existing_proposal_task_id, proposal_status):
        reasons.append("active_proposal_exists")

    fix_template_candidates = find_fix_templates_for_root_cause(root_cause) if root_cause else []
    if root_cause and not fix_template_candidates:
        reasons.append("no_fix_template")

    objective = (investigation.get("objective") or "").strip()
    if objective and is_forbidden(classify_change_objective(objective)):
        reasons.append("forbidden_objective")

    if recommended_fix and is_forbidden(classify_change_objective(recommended_fix)):
        reasons.append("forbidden_recommended_fix")

    return ProposalEligibilityResult(
        eligible=len(reasons) == 0,
        reasons=reasons,
        confidence=confidence,
        fix_template_candidates=fix_template_candidates,
        existing_proposal_task_id=existing_proposal_task_id,
    )
