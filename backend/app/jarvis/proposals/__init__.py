"""Jarvis Phase 4B patch proposal workflow (eligibility + templates + proposal service)."""

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
    get_fix_template_detail,
    list_fix_template_summaries,
    list_fix_templates,
    match_templates_for_investigation,
)
from app.jarvis.proposals.proposal_service import (
    ProposalWorkflowError,
    submit_patch_proposal,
)

__all__ = [
    "ProposalEligibilityResult",
    "ProposalWorkflowError",
    "check_proposal_eligibility",
    "find_fix_templates_for_root_cause",
    "get_fix_template",
    "get_fix_template_detail",
    "jarvis_4b_min_confidence",
    "jarvis_4b_proposals_enabled",
    "list_fix_template_summaries",
    "list_fix_templates",
    "match_templates_for_investigation",
    "phase4b_safety_status",
    "submit_patch_proposal",
]
