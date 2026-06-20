"""Calibrated confidence model for investigations.

Implements Deliverable 2 of jarvis_eval/SELF_HEALING_IMPROVEMENT_DESIGN.md.

Replaces "match score == confidence" with a bounded four-factor model
(Evidence strength, Objective alignment, Domain match, Recommendation
specificity) plus hard caps that make 90-100 impossible under weak evidence or
domain mismatch. Pure: no DB, no production access.
"""

from __future__ import annotations

import re
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

# PR #67 confidence-regression caps (flagged path only).
_CAP_AUTH_CONTRADICTION = 48.0
_CAP_CREDENTIAL_CONTRADICTION = 40.0
_CAP_GENERIC_OBJECTIVE_LOW = 35.0
_ACW_MONOTONICITY_MARGIN = 1.0
_DEFAULT_ACW_THRESHOLD = 70.0
_LOW_OBJECTIVE_CONFIDENCE = 0.4
_VERY_LOW_OBJECTIVE_ALIGNMENT = 0.15


@dataclass
class ConfidenceBreakdown:
    evidence_strength: float
    objective_alignment: float
    domain_match: float
    specificity: float
    raw: float
    final: float
    caps_applied: list[str] = field(default_factory=list)
    legacy_confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "evidence_strength": round(self.evidence_strength, 3),
            "objective_alignment": round(self.objective_alignment, 3),
            "domain_match": round(self.domain_match, 3),
            "specificity": round(self.specificity, 3),
            "raw": round(self.raw, 1),
            "final": round(self.final, 1),
            "caps_applied": list(self.caps_applied),
        }
        if self.legacy_confidence:
            payload["legacy_confidence"] = round(self.legacy_confidence, 1)
        return payload


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


def credentials_present_in_evidence(
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None = None,
) -> bool:
    """True when collected evidence indicates credentials are configured and working."""
    for item in evidence:
        if not isinstance(item, dict):
            continue
        detail = item.get("detail", "").lower()
        compact = detail.replace(" ", "")
        if "exchange_credential_warnings=no" in compact:
            return True
        if "credential/auth warnings: none" in detail or "credential warnings: none" in detail:
            return True
        if item.get("source") == "authentication":
            if "missing_credentials" not in detail and "40101" not in detail:
                if any(k in detail for k in ("_present", "used_pair", "credentials configured")):
                    return True
    for output in tool_outputs or []:
        exchange_meta = ((output.get("sources") or {}).get("exchange") or {})
        cred_diag = exchange_meta.get("credential_diagnostics") or output.get("credential_diagnostics") or {}
        if any(k.endswith("_PRESENT") and v for k, v in cred_diag.items()):
            return True
        counts = output.get("counts") or {}
        exchange_live = int(counts.get("exchange_live") or 0)
        sync_status = exchange_meta.get("sync_status") or output.get("sync_status")
        if exchange_live > 0 and sync_status not in ("missing_credentials", "failed_auth"):
            return True
    return False


def cause_claims_missing_credentials(root_cause: str | None) -> bool:
    if not root_cause:
        return False
    low = root_cause.lower()
    return any(
        kw in low
        for kw in (
            "missing",
            "misconfigured",
            "not configured",
            "40101",
            "duplicated api secret",
        )
    )


def has_cause_specific_corroboration(
    *,
    root_cause: str | None,
    cause_domain: InvestigationDomain,
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None = None,
) -> bool:
    """True when direct evidence corroborates the selected root cause (not circumstantial)."""
    if not root_cause:
        return False
    cause_lower = root_cause.lower()

    if "equity" in cause_lower or "portfolio" in cause_lower:
        for item in evidence:
            detail = item.get("detail", "").lower()
            if any(
                kw in detail
                for kw in (
                    "missing equity",
                    "derived from balances",
                    "derived from cached balances",
                    "exchange-reported equity",
                )
            ):
                return True

    if any(kw in cause_lower for kw in ("credential", "40101", "auth", "secret")):
        for item in evidence:
            detail = item.get("detail", "").lower()
            if any(kw in detail for kw in ("40101", "missing_credentials", "authentication fail", "failed_auth")):
                return True
        for output in tool_outputs or []:
            sync_status = output.get("sync_status")
            if sync_status in ("missing_credentials", "failed_auth"):
                return True

    if "websocket" in cause_lower or "price feed" in cause_lower:
        for item in evidence:
            detail = item.get("detail", "").lower()
            if any(kw in detail for kw in ("disconnect", "stale", "not receiving", "ws stale")):
                if item.get("is_direct") or str(item.get("confidence")) == "high":
                    return True
        return False

    salient = [t for t in re.split(r"[^a-z0-9]+", cause_lower) if len(t) >= 6][:4]
    for item in evidence:
        if not (item.get("is_direct") or str(item.get("confidence")) == "high"):
            continue
        detail = item.get("detail", "").lower()
        if salient and sum(1 for tok in salient if tok in detail) >= 2:
            return True
    return False


def apply_confidence_regression_caps(
    breakdown: ConfidenceBreakdown,
    *,
    legacy_confidence: float,
    category: str,
    objective_domain: InvestigationDomain,
    objective_confidence: float,
    cause_domain: InvestigationDomain,
    root_cause: str | None,
    evidence: list[EvidenceItem],
    tool_outputs: list[dict[str, Any]] | None,
    auth_failure_signals: bool,
    acw_threshold: float = _DEFAULT_ACW_THRESHOLD,
) -> ConfidenceBreakdown:
    """Apply PR #67 regression caps so ON confidence cannot inflate weak legacy cases."""
    final = breakdown.final
    caps = list(breakdown.caps_applied)

    auth_scope = (
        cause_domain == InvestigationDomain.EXCHANGE_AUTH
        or (category or "").strip().lower() == "authentication"
    )
    if auth_scope and not auth_failure_signals and final > _CAP_AUTH_CONTRADICTION:
        final = _CAP_AUTH_CONTRADICTION
        caps.append("auth_contradiction_cap_48")

    if (
        credentials_present_in_evidence(evidence, tool_outputs)
        and cause_claims_missing_credentials(root_cause)
        and final > _CAP_CREDENTIAL_CONTRADICTION
    ):
        final = _CAP_CREDENTIAL_CONTRADICTION
        caps.append("credential_contradiction_cap_40")

    if (
        breakdown.objective_alignment <= _VERY_LOW_OBJECTIVE_ALIGNMENT
        and final > _CAP_GENERIC_OBJECTIVE_LOW
    ):
        final = _CAP_GENERIC_OBJECTIVE_LOW
        caps.append("generic_objective_cap_35")

    generic_objective = (
        objective_domain == InvestigationDomain.GENERIC
        or objective_confidence < _LOW_OBJECTIVE_CONFIDENCE
    )
    if generic_objective and final > legacy_confidence:
        final = legacy_confidence
        caps.append("generic_objective_legacy_cap")

    corroborated = has_cause_specific_corroboration(
        root_cause=root_cause,
        cause_domain=cause_domain,
        evidence=evidence,
        tool_outputs=tool_outputs,
    )
    if final > legacy_confidence and not corroborated:
        final = legacy_confidence
        caps.append("legacy_confidence_ceiling")

    acw_cap = acw_threshold - _ACW_MONOTONICITY_MARGIN
    if legacy_confidence < acw_threshold and final >= acw_threshold:
        final = min(final, acw_cap)
        caps.append("acw_monotonicity_cap")

    return ConfidenceBreakdown(
        evidence_strength=breakdown.evidence_strength,
        objective_alignment=breakdown.objective_alignment,
        domain_match=breakdown.domain_match,
        specificity=breakdown.specificity,
        raw=breakdown.raw,
        final=round(final, 1),
        caps_applied=caps,
        legacy_confidence=legacy_confidence,
    )
