"""Calibrated confidence model for investigations.

Implements Deliverable 2 of jarvis_eval/SELF_HEALING_IMPROVEMENT_DESIGN.md.

Replaces "match score == confidence" with a bounded four-factor model
(Evidence strength, Objective alignment, Domain match, Recommendation
specificity) plus hard caps that make 90-100 impossible under weak evidence or
domain mismatch. Pure: no DB, no production access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.jarvis.investigations.domains import InvestigationDomain, domain_relevance
from app.jarvis.investigations.evidence_model import (
    EvidenceItem,
    count_independent_sources,
    has_direct_evidence,
    is_substantive_evidence,
)

# Factor weights (sum to 1.0).
_W_EVIDENCE = 0.40
_W_OBJECTIVE = 0.20
_W_DOMAIN = 0.25
_W_SPECIFICITY = 0.15

# Hard caps.
_CAP_DOMAIN_MISMATCH = 50.0
_CAP_WEAK_EVIDENCE = 40.0
_CAP_GENERIC_RECOMMENDATION = 60.0
_SPECIFICITY_GENERIC_THRESHOLD = 0.3


@dataclass
class ConfidenceBreakdown:
    evidence_strength: float
    objective_alignment: float
    domain_match: float
    specificity: float
    raw: float
    final: float
    caps_applied: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "evidence_strength": round(self.evidence_strength, 3),
            "objective_alignment": round(self.objective_alignment, 3),
            "domain_match": round(self.domain_match, 3),
            "specificity": round(self.specificity, 3),
            "raw": round(self.raw, 1),
            "final": round(self.final, 1),
            "caps_applied": list(self.caps_applied),
        }


def compute_evidence_strength(
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None = None,
) -> float:
    """Evidence strength in [0,1] from independent sources + direct observations."""
    substantive = sum(1 for item in evidence if is_substantive_evidence(item))
    if substantive == 0:
        return 0.0
    independent = count_independent_sources(evidence)
    direct = has_direct_evidence(evidence, tool_outputs)
    score = min(independent / 3.0, 1.0) * 0.6
    score += 0.4 if direct else 0.0
    return min(score, 1.0)


def calibrate_confidence(
    *,
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None,
    objective_domain: InvestigationDomain,
    objective_confidence: float,
    cause_domain: InvestigationDomain,
    specificity: float,
    has_meaningful_root_cause: bool,
) -> ConfidenceBreakdown:
    """Produce a calibrated confidence (0-100) plus a transparent breakdown."""
    evidence_strength = compute_evidence_strength(evidence, tool_outputs)
    domain_match = domain_relevance(objective_domain, cause_domain, objective_confidence)

    if cause_domain == objective_domain:
        alignment = 1.0
    elif domain_match >= 0.6:
        alignment = 0.4
    else:
        alignment = 0.1
    objective_alignment = max(0.0, min(objective_confidence, 1.0)) * alignment

    raw = 100.0 * (
        _W_EVIDENCE * evidence_strength
        + _W_OBJECTIVE * objective_alignment
        + _W_DOMAIN * domain_match
        + _W_SPECIFICITY * specificity
    )

    caps_applied: list[str] = []

    if not has_meaningful_root_cause:
        return ConfidenceBreakdown(
            evidence_strength=evidence_strength,
            objective_alignment=objective_alignment,
            domain_match=domain_match,
            specificity=specificity,
            raw=raw,
            final=0.0,
            caps_applied=["non_meaningful_root_cause"],
        )

    final = raw

    if domain_match < 1.0 and final > _CAP_DOMAIN_MISMATCH:
        final = _CAP_DOMAIN_MISMATCH
        caps_applied.append("domain_mismatch_cap_50")

    independent = count_independent_sources(evidence)
    direct = has_direct_evidence(evidence, tool_outputs)
    if independent < 2 and not direct and final > _CAP_WEAK_EVIDENCE:
        final = _CAP_WEAK_EVIDENCE
        caps_applied.append("weak_evidence_cap_40")

    if specificity < _SPECIFICITY_GENERIC_THRESHOLD and final > _CAP_GENERIC_RECOMMENDATION:
        final = _CAP_GENERIC_RECOMMENDATION
        caps_applied.append("generic_recommendation_cap_60")

    return ConfidenceBreakdown(
        evidence_strength=evidence_strength,
        objective_alignment=objective_alignment,
        domain_match=domain_match,
        specificity=specificity,
        raw=raw,
        final=final,
        caps_applied=caps_applied,
    )
