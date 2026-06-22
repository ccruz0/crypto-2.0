"""Root cause assessment for self-healing (Phase 7).

Derives confidence, severity, blast radius, and fixability from a completed
investigation. Deterministic; no LLM, no DB, no production access.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

Severity = str  # "low" | "medium" | "high" | "critical"
BlastRadius = str  # "isolated" | "service" | "system" | "unknown"
Fixability = str  # "template" | "code_change" | "manual" | "not_fixable"

_GENERIC_ROOT_CAUSES = frozenset(
    {
        "",
        "unknown",
        "not determined",
        "unable to determine",
        "needs further investigation",
        "requires further investigation",
        "no root cause found",
        "no active dashboard/exchange mismatch detected",
    }
)

# Severity keyword buckets (checked against root cause + summary + category).
_CRITICAL_KEYWORDS = (
    "authentication fail",
    "auth failure",
    "40101",
    "credential",
    "secret",
    "trading halted",
    "cannot place",
    "data loss",
    "outage",
    "all orders",
)
_HIGH_KEYWORDS = (
    "mismatch",
    "discrepancy",
    "cache empty",
    "stale cache",
    "missing orders",
    "open orders",
    "equity",
    "portfolio",
    "sync fail",
    "blocks cache",
    "deployment failure",
    "deploy fail",
)
_LOW_KEYWORDS = (
    "websocket",
    "price feed",
    "telegram",
    "cosmetic",
    "log noise",
    "warning only",
    "non-fatal",
)

_CATEGORY_SEVERITY: dict[str, Severity] = {
    "authentication": "critical",
    "portfolio": "high",
    "orders": "high",
    "dashboard": "high",
    "open_orders_mismatch": "high",
    "exchange_sync": "high",
    "deployment": "high",
    "websocket": "low",
    "telegram": "low",
    "notifications": "low",
}

# System-wide blast radius signals.
_SYSTEM_PATH_FRAGMENTS = (
    "exchange_sync",
    "credential_resolver",
    "crypto_com_guardrail",
    "factory.py",
    "database.py",
    "core/",
)
_SERVICE_PATH_FRAGMENTS = (
    "services/",
    "routes_",
    "api/",
)
_ISOLATED_PATH_FRAGMENTS = (
    "frontend/",
    "scripts/",
    "telegram",
)


@dataclass
class RootCauseAssessment:
    confidence: float
    severity: Severity
    blast_radius: BlastRadius
    fixability: Fixability
    has_meaningful_root_cause: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "confidence": round(self.confidence, 2),
            "severity": self.severity,
            "blast_radius": self.blast_radius,
            "fixability": self.fixability,
            "has_meaningful_root_cause": self.has_meaningful_root_cause,
        }


def _is_meaningful_root_cause(root_cause: str) -> bool:
    normalized = (root_cause or "").strip().lower()
    if normalized in _GENERIC_ROOT_CAUSES:
        return False
    return len(normalized) >= 8


def _assess_severity(*, category: str, blob: str) -> Severity:
    text = (blob or "").lower()
    if any(kw in text for kw in _CRITICAL_KEYWORDS):
        return "critical"
    base = _CATEGORY_SEVERITY.get((category or "").strip().lower())
    if any(kw in text for kw in _HIGH_KEYWORDS):
        return _max_severity(base or "medium", "high")
    if base:
        return base
    if any(kw in text for kw in _LOW_KEYWORDS):
        return "low"
    return "medium"


_SEVERITY_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def _max_severity(a: Severity, b: Severity) -> Severity:
    return a if _SEVERITY_ORDER.get(a, 1) >= _SEVERITY_ORDER.get(b, 1) else b


def _assess_blast_radius(affected_files: list[str], category: str) -> BlastRadius:
    if not affected_files:
        cat = (category or "").lower()
        if cat in ("authentication", "exchange_sync"):
            return "system"
        if cat in ("websocket", "telegram", "notifications"):
            return "isolated"
        return "unknown"
    lowered = [str(f).lower() for f in affected_files]
    if any(any(frag in path for frag in _SYSTEM_PATH_FRAGMENTS) for path in lowered):
        return "system"
    backend_service_hits = [
        path
        for path in lowered
        if any(frag in path for frag in _SERVICE_PATH_FRAGMENTS)
    ]
    only_isolated = all(
        any(frag in path for frag in _ISOLATED_PATH_FRAGMENTS) for path in lowered
    )
    if only_isolated:
        return "isolated"
    if len(affected_files) > 3:
        return "system"
    if backend_service_hits:
        return "service"
    return "service"


def assess_root_cause(
    investigation: dict[str, Any],
    *,
    affected_files: list[str] | None = None,
    has_template: bool = False,
    safety_allowed: bool = True,
) -> RootCauseAssessment:
    """Build a structured root-cause assessment from an investigation dict."""
    root_cause = str(investigation.get("root_cause") or "")
    summary = str(investigation.get("summary") or "")
    impact = str(investigation.get("impact") or "")
    category = str(investigation.get("category") or "")
    confidence = float(investigation.get("confidence") or 0.0)

    meaningful = _is_meaningful_root_cause(root_cause)
    blob = " ".join((root_cause, summary, impact))
    severity = _assess_severity(category=category, blob=blob)
    blast_radius = _assess_blast_radius(affected_files or [], category)

    if not meaningful:
        fixability: Fixability = "not_fixable"
    elif not safety_allowed:
        fixability = "manual"
    elif has_template:
        fixability = "template"
    else:
        fixability = "code_change"

    return RootCauseAssessment(
        confidence=confidence,
        severity=severity,
        blast_radius=blast_radius,
        fixability=fixability,
        has_meaningful_root_cause=meaningful,
    )
