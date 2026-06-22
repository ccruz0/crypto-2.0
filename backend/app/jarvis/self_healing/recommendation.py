"""Fix recommendation engine for self-healing (Phase 7).

Turns a completed investigation into a concrete, advisory fix recommendation:
likely fix, affected files, estimated risk, and estimated effort. Deterministic;
reuses the Phase 4B fix-template catalog for grounding. No LLM, no DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jarvis.proposals.template_matching import (
    get_template_match,
    match_templates_for_investigation,
)

EstimatedRisk = str  # "low" | "medium" | "high"
EstimatedEffort = str  # "small" | "medium" | "large"

_RISK_RANK = {"low": 0, "medium": 1, "high": 2}


@dataclass
class FixRecommendation:
    proposed_fix: str
    affected_files: list[str] = field(default_factory=list)
    estimated_risk: EstimatedRisk = "medium"
    estimated_effort: EstimatedEffort = "medium"
    fix_template_id: str | None = None
    test_paths: list[str] = field(default_factory=list)
    validation_rules: list[str] = field(default_factory=list)
    has_template: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "proposed_fix": self.proposed_fix,
            "affected_files": list(self.affected_files),
            "estimated_risk": self.estimated_risk,
            "estimated_effort": self.estimated_effort,
            "fix_template_id": self.fix_template_id,
            "test_paths": list(self.test_paths),
            "validation_rules": list(self.validation_rules),
            "has_template": self.has_template,
        }


def _estimate_effort(*, num_files: int, risk: EstimatedRisk, has_template: bool) -> EstimatedEffort:
    if has_template and num_files <= 1 and risk == "low":
        return "small"
    if num_files <= 1 and _RISK_RANK.get(risk, 1) <= 1:
        return "small"
    if num_files > 3 or risk == "high":
        return "large"
    return "medium"


def recommend_fix(investigation: dict[str, Any]) -> FixRecommendation:
    """Produce an advisory fix recommendation for a completed investigation."""
    root_cause = str(investigation.get("root_cause") or "").strip()
    recommended_fix = str(investigation.get("recommended_fix") or "").strip()

    match = match_templates_for_investigation(investigation)
    template = get_template_match(match.primary_template) if match.primary_template else None

    if template is not None:
        affected_files = list(template.target_files)
        estimated_risk: EstimatedRisk = template.risk_level if template.risk_level in _RISK_RANK else "medium"
        proposed_fix = recommended_fix or template.recommended_fix or root_cause
        effort = _estimate_effort(
            num_files=len(affected_files),
            risk=estimated_risk,
            has_template=True,
        )
        return FixRecommendation(
            proposed_fix=proposed_fix,
            affected_files=affected_files,
            estimated_risk=estimated_risk,
            estimated_effort=effort,
            fix_template_id=template.fix_template_id,
            test_paths=list(template.test_paths),
            validation_rules=list(template.validation_rules),
            has_template=True,
        )

    # No template match: advisory recommendation grounded in the investigation's
    # own recommended_fix. Affected files unknown -> conservative risk.
    proposed_fix = recommended_fix or root_cause
    estimated_risk = "medium"
    effort = _estimate_effort(num_files=0, risk=estimated_risk, has_template=False)
    return FixRecommendation(
        proposed_fix=proposed_fix,
        affected_files=[],
        estimated_risk=estimated_risk,
        estimated_effort=effort,
        fix_template_id=None,
        test_paths=[],
        validation_rules=[],
        has_template=False,
    )
