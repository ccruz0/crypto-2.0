"""Jarvis Phase 4B patch proposal foundation (eligibility + fix templates)."""

from app.jarvis.proposals.config import (
    jarvis_4b_min_confidence,
    jarvis_4b_proposals_enabled,
    phase4b_safety_status,
)
from app.jarvis.proposals.eligibility import (
    ProposalEligibilityResult,
    check_proposal_eligibility,
)
from app.jarvis.proposals.fix_templates import (
    find_fix_templates_for_root_cause,
    get_fix_template,
    list_fix_templates,
)

__all__ = [
    "ProposalEligibilityResult",
    "check_proposal_eligibility",
    "find_fix_templates_for_root_cause",
    "get_fix_template",
    "jarvis_4b_min_confidence",
    "jarvis_4b_proposals_enabled",
    "list_fix_templates",
    "phase4b_safety_status",
]
