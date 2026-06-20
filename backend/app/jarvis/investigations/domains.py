"""Objective-aware investigation domains and domain-relevance gating.

Implements Deliverable 1 of jarvis_eval/SELF_HEALING_IMPROVEMENT_DESIGN.md.

This module is a pure, additive layer. It is only *consumed* by the investigation
report pipeline when the feature flag ``JARVIS_OBJECTIVE_AWARE_RC`` is enabled;
when the flag is off, callers leave the existing behavior unchanged.

No DB access, no production access, no execution.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from enum import Enum


class InvestigationDomain(str, Enum):
    EXCHANGE_AUTH = "exchange_auth"
    PORTFOLIO_RECONCILIATION = "portfolio_reconciliation"
    ORDER_RECONCILIATION = "order_reconciliation"
    OPEN_ORDERS = "open_orders"
    DATABASE = "database"
    DEPLOYMENT = "deployment"
    INFRASTRUCTURE = "infrastructure"
    PERFORMANCE = "performance"
    GENERIC = "generic"


def objective_aware_rc_enabled() -> bool:
    """Feature flag (default OFF). Gates objective-aware RC selection + calibration."""
    raw = (os.environ.get("JARVIS_OBJECTIVE_AWARE_RC") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


@dataclass
class DomainClassification:
    domain: InvestigationDomain
    domain_confidence: float
    matched_signals: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return {
            "domain": self.domain.value,
            "domain_confidence": round(self.domain_confidence, 2),
            "matched_signals": list(self.matched_signals),
        }


# Exact template_id -> domain (highest-precedence, confidence 1.0).
_TEMPLATE_DOMAIN: dict[str, InvestigationDomain] = {
    "exchange_auth_failing": InvestigationDomain.EXCHANGE_AUTH,
    "portfolio_reconciliation_mismatch": InvestigationDomain.PORTFOLIO_RECONCILIATION,
    "open_orders_empty": InvestigationDomain.OPEN_ORDERS,
    "open_orders_zero_dashboard": InvestigationDomain.OPEN_ORDERS,
    "dashboard_exchange_mismatch": InvestigationDomain.ORDER_RECONCILIATION,
    "executed_orders_missing": InvestigationDomain.ORDER_RECONCILIATION,
    "jarvis_task_failing": InvestigationDomain.DEPLOYMENT,
    "websocket_prices_stale": InvestigationDomain.INFRASTRUCTURE,
}

# Coarse investigation category -> domain (fallback, confidence ~0.5).
_CATEGORY_DOMAIN: dict[str, InvestigationDomain] = {
    "authentication": InvestigationDomain.EXCHANGE_AUTH,
    "portfolio": InvestigationDomain.PORTFOLIO_RECONCILIATION,
    "orders": InvestigationDomain.ORDER_RECONCILIATION,
    "dashboard": InvestigationDomain.ORDER_RECONCILIATION,
    "exchange": InvestigationDomain.ORDER_RECONCILIATION,
    "database": InvestigationDomain.DATABASE,
    "deployment": InvestigationDomain.DEPLOYMENT,
    "websocket": InvestigationDomain.INFRASTRUCTURE,
    "performance": InvestigationDomain.PERFORMANCE,
    "api": InvestigationDomain.GENERIC,
}

# Ordered text classifiers — first match wins (most specific first).
_TEXT_DOMAIN_PATTERNS: tuple[tuple[InvestigationDomain, re.Pattern[str]], ...] = (
    (
        InvestigationDomain.EXCHANGE_AUTH,
        re.compile(
            r"credential|40101|authentication|auth\s+fail|api\s+key|api\s+secret|runtime\.env|secret\b",
            re.IGNORECASE,
        ),
    ),
    (
        InvestigationDomain.PORTFOLIO_RECONCILIATION,
        re.compile(r"portfolio|equity|net_equity|net\s+equity|wallet\s+balance|balances", re.IGNORECASE),
    ),
    (
        InvestigationDomain.OPEN_ORDERS,
        re.compile(
            r"open[\s_-]?orders?.*(cache|empty|stale|zero|0\b)|"
            r"(cache|empty|stale).*open[\s_-]?orders?|"
            r"open\s+orders?\s+empty",
            re.IGNORECASE,
        ),
    ),
    (
        InvestigationDomain.ORDER_RECONCILIATION,
        re.compile(
            r"\border\b|orders?|trade\s+history|filled|trigger|reconcil|dashboard|exchange|mismatch",
            re.IGNORECASE,
        ),
    ),
    (
        InvestigationDomain.DATABASE,
        re.compile(r"database|\bdb\b|query|\bsql\b|\btable\b|postgres", re.IGNORECASE),
    ),
    (
        InvestigationDomain.DEPLOYMENT,
        re.compile(
            r"deploy(?:ment)?|container|docker|health\s+check|service.*(unhealthy|failing|down)|task\s+failing",
            re.IGNORECASE,
        ),
    ),
    (
        InvestigationDomain.INFRASTRUCTURE,
        re.compile(r"websocket|\bws\b|price\s+feed|market.?updater|network|connection", re.IGNORECASE),
    ),
    (
        InvestigationDomain.PERFORMANCE,
        re.compile(r"\bslow\b|latency|timeout|performance|\bcpu\b|memory|throughput", re.IGNORECASE),
    ),
)


def _classify_text_domain(text: str) -> InvestigationDomain:
    """Map arbitrary text (objective or root cause) to a domain (first match wins)."""
    blob = text or ""
    for domain, pattern in _TEXT_DOMAIN_PATTERNS:
        if pattern.search(blob):
            return domain
    return InvestigationDomain.GENERIC


def classify_cause_domain(cause_text: str) -> InvestigationDomain:
    """Classify a root-cause string into a domain."""
    return _classify_text_domain(cause_text)


def classify_domain(objective: str, *, category: str = "", template_id: str = "") -> DomainClassification:
    """Resolve the investigation's domain from template, objective text, and category.

    Precedence: exact template (1.0) > objective text (0.7-0.9) > category (0.5) > generic (0.2).
    """
    tid = (template_id or "").strip()
    if tid in _TEMPLATE_DOMAIN:
        return DomainClassification(_TEMPLATE_DOMAIN[tid], 1.0, [f"template:{tid}"])

    text_dom = _classify_text_domain(objective or "")
    cat_dom = _CATEGORY_DOMAIN.get((category or "").strip().lower())

    if text_dom != InvestigationDomain.GENERIC:
        signals = [f"text:{text_dom.value}"]
        confidence = 0.7
        if cat_dom == text_dom:
            confidence = 0.9
            signals.append(f"category:{cat_dom.value}")
        return DomainClassification(text_dom, confidence, signals)

    if cat_dom and cat_dom != InvestigationDomain.GENERIC:
        return DomainClassification(cat_dom, 0.5, [f"category:{cat_dom.value}"])

    return DomainClassification(InvestigationDomain.GENERIC, 0.2, ["no_signal"])


# Curated adjacent domain pairs (symmetric) -> moderate relevance.
_ADJACENT_PAIRS: frozenset[frozenset[InvestigationDomain]] = frozenset(
    {
        frozenset({InvestigationDomain.OPEN_ORDERS, InvestigationDomain.ORDER_RECONCILIATION}),
        frozenset({InvestigationDomain.DATABASE, InvestigationDomain.DEPLOYMENT}),
        frozenset({InvestigationDomain.DEPLOYMENT, InvestigationDomain.INFRASTRUCTURE}),
        frozenset({InvestigationDomain.PERFORMANCE, InvestigationDomain.INFRASTRUCTURE}),
    }
)

_LOW_CONFIDENCE_FLOOR = 0.4


def domain_relevance(
    objective_domain: InvestigationDomain,
    cause_domain: InvestigationDomain,
    objective_confidence: float = 1.0,
) -> float:
    """Relevance weight of a cause domain for an objective domain.

    1.0 in-domain, 0.6 adjacent (or generic cause), 0.2 cross-domain.
    When the objective domain is GENERIC or its confidence is low, gating is
    disabled (returns 1.0) so weakly-classified objectives are not penalized.
    """
    if objective_domain == InvestigationDomain.GENERIC or objective_confidence < _LOW_CONFIDENCE_FLOOR:
        return 1.0
    if cause_domain == objective_domain:
        return 1.0
    if cause_domain == InvestigationDomain.GENERIC:
        return 0.6
    if frozenset({objective_domain, cause_domain}) in _ADJACENT_PAIRS:
        return 0.6
    return 0.2


def apply_domain_gating(
    candidates: list,
    objective_domain: InvestigationDomain,
    objective_confidence: float = 1.0,
) -> list:
    """Re-weight candidate scores by domain relevance and re-sort.

    Mutates each candidate's ``score`` (to the domain-adjusted score) and sets
    ``domain`` when unset. Returns the same list, re-sorted by adjusted score.
    Cross-domain causes are heavily penalized (×0.2) so an in-domain candidate
    wins selection; the explicit-evidence override is applied later in selection.
    """
    for candidate in candidates:
        if not getattr(candidate, "domain", ""):
            candidate.domain = classify_cause_domain(candidate.cause).value
        cause_domain = InvestigationDomain(candidate.domain)
        relevance = domain_relevance(objective_domain, cause_domain, objective_confidence)
        candidate.score = round(candidate.score * relevance, 1)
    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
