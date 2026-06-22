"""Self-healing safety rules (Phase 7).

Jarvis may only *propose* fixes. Certain domains are too sensitive to ever be
auto-proposed without explicit human approval:

* trading execution
* live order placement
* wallet operations
* credential rotation
* secrets

For these domains, a recommendation may still be *displayed* (advisory), but it is
never marked ACW-ready and an ACW task cannot be created from it automatically.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.jarvis.execution.safety import classify_change_objective, is_forbidden

# Action-gated domains: mere mention of "order"/"position" is normal in
# investigations, so these only fire on explicit execution verbs.
_FORBIDDEN_DOMAIN_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "trading_execution": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(execute|place|submit|cancel|modify)\b.*\b(trade|order|position)s?\b",
            r"\bmarket\s+order\b",
            r"\b(buy|sell)\b.*\b(btc|eth|usdt|coin|token|asset)\b",
            r"\bclose\b.*\bpositions?\b",
            r"\border\s+(placement|execution|routing)\b",
        )
    ),
    "live_order_placement": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\bplace\b.*\b(live|real)\b.*\border",
            r"\blive\s+order\s+placement\b",
            r"\bsubmit\b.*\border\b.*\bexchange\b",
        )
    ),
}

# Sensitive-domain mentions: these domains are too dangerous to ever auto-propose,
# so *any* mention (not just action verbs) disqualifies automatic self-healing.
# A human must explicitly approve fixes touching these areas.
_SENSITIVE_DOMAIN_MENTION_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "wallet_operations": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\bwallet\b",
            r"\b(withdraw|withdrawal)\b",
            r"\bprivate\s+key\b",
            r"\bseed\s+phrase\b",
            r"\bsign\b.*\btransaction\b",
        )
    ),
    "credential_rotation": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(rotate|regenerate|reset|replace|cycle|deduplicate|dedupe)\b.*\b(api\s+keys?|api\s+secrets?|credentials?|secrets?|tokens?|passwords?)\b",
            r"\bcredential\s+rotation\b",
            r"\bkey\s+rotation\b",
        )
    ),
    "secrets": tuple(
        re.compile(p, re.IGNORECASE)
        for p in (
            r"\b(secret|credential|api\s+key|api\s+secret|private\s+key|password|auth\s+token|access\s+token)s?\b",
            r"\bruntime\.env\b",
            r"\b40101\b",
            r"\bauthentication\s+fail",
            r"\bauth\s+failure\b",
        )
    ),
}

# File path fragments that imply a sensitive domain regardless of wording.
_FORBIDDEN_PATH_FRAGMENTS: dict[str, tuple[str, ...]] = {
    "trading_execution": ("order_executor", "trade_executor", "execution_engine", "place_order"),
    "wallet_operations": ("wallet", "withdraw"),
    "secrets": (
        "secret",
        "credential",
        "credentials_store",
        "runtime_env_write",
        "secure_runtime_env",
        "diagnose_crypto_com_auth",
        "crypto_com_guardrail",
    ),
}


@dataclass
class SelfHealingSafetyResult:
    """Outcome of a self-healing safety evaluation."""

    allowed: bool
    blocked_domains: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "blocked_domains": list(self.blocked_domains),
            "reasons": list(self.reasons),
        }


def _scan_text_domains(text: str) -> list[str]:
    blocked: list[str] = []
    normalized = (text or "").strip()
    if not normalized:
        return blocked
    for domain, patterns in _FORBIDDEN_DOMAIN_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            blocked.append(domain)
    for domain, patterns in _SENSITIVE_DOMAIN_MENTION_PATTERNS.items():
        if any(pattern.search(normalized) for pattern in patterns):
            blocked.append(domain)
    return blocked


def _scan_file_domains(files: list[str] | tuple[str, ...] | None) -> list[str]:
    blocked: list[str] = []
    for path in files or ():
        lowered = str(path).lower()
        for domain, fragments in _FORBIDDEN_PATH_FRAGMENTS.items():
            if any(fragment in lowered for fragment in fragments):
                blocked.append(domain)
    return blocked


def evaluate_self_healing_safety(
    *,
    objective: str | None = None,
    root_cause: str | None = None,
    recommended_fix: str | None = None,
    proposed_objective: str | None = None,
    affected_files: list[str] | tuple[str, ...] | None = None,
) -> SelfHealingSafetyResult:
    """Decide whether an automatic self-healing recommendation may proceed to ACW.

    A recommendation is blocked when it touches any forbidden domain, or when the
    underlying objective/fix is classified FORBIDDEN by the shared change-objective
    classifier (trading/deploy/delete/secrets/etc.).
    """
    blocked: list[str] = []
    reasons: list[str] = []

    for text in (objective, root_cause, recommended_fix, proposed_objective):
        blocked.extend(_scan_text_domains(text or ""))
    blocked.extend(_scan_file_domains(affected_files))

    # Shared forbidden classifier (covers deploy/merge/delete/secret writes).
    for label, text in (
        ("objective", objective),
        ("recommended_fix", recommended_fix),
        ("proposed_objective", proposed_objective),
    ):
        candidate = (text or "").strip()
        if candidate and is_forbidden(classify_change_objective(candidate)):
            reasons.append(f"forbidden_change_objective:{label}")

    # De-duplicate while preserving order.
    blocked = list(dict.fromkeys(blocked))
    for domain in blocked:
        reasons.append(f"forbidden_domain:{domain}")

    allowed = not blocked and not reasons
    return SelfHealingSafetyResult(allowed=allowed, blocked_domains=blocked, reasons=reasons)
