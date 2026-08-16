"""Model router for Jarvis Bedrock calls (Phase 2 / P2-R2).

Routes each request to a model tier by task complexity:

    simple    -> Claude 3 Haiku   (classification, short extraction, one-liners)
    standard  -> Claude 3 Sonnet  (planning, research, strategy)
    critical  -> Claude 3 Opus    (only when explicitly requested)

Resolution precedence (highest wins) — deliberately backward compatible:

    1. JARVIS_BEDROCK_MODEL_ID          global pin: existing deployments that pin
                                        a model keep working exactly as before.
    2. JARVIS_MODEL_ROUTER_ENABLED=false router off -> legacy default model.
    3. JARVIS_MODEL_SIMPLE / _STANDARD / _CRITICAL   per-tier override.
    4. Built-in defaults below.

`fallback_chain()` returns the ordered list of models to try when a call fails
mid-flight (throttling that survives retries, model unavailable): the resolved
model first, then one escalation step up the capability ladder.
"""

from __future__ import annotations

import os

TIER_SIMPLE = "simple"
TIER_STANDARD = "standard"
TIER_CRITICAL = "critical"

_VALID_TIERS = (TIER_SIMPLE, TIER_STANDARD, TIER_CRITICAL)

DEFAULT_MODELS: dict[str, str] = {
    TIER_SIMPLE: "anthropic.claude-3-haiku-20240307-v1:0",
    TIER_STANDARD: "anthropic.claude-3-sonnet-20240229-v1:0",
    TIER_CRITICAL: "anthropic.claude-3-opus-20240229-v1:0",
}

# Legacy single-model default used when the router is disabled.
LEGACY_DEFAULT_MODEL_ID = "anthropic.claude-3-sonnet-20240229-v1:0"

_TIER_ENV = {
    TIER_SIMPLE: "JARVIS_MODEL_SIMPLE",
    TIER_STANDARD: "JARVIS_MODEL_STANDARD",
    TIER_CRITICAL: "JARVIS_MODEL_CRITICAL",
}

_ESCALATION = {
    TIER_SIMPLE: TIER_STANDARD,
    TIER_STANDARD: TIER_CRITICAL,
}


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def router_enabled() -> bool:
    """Router is on by default; JARVIS_MODEL_ROUTER_ENABLED=false disables it."""
    val = _env("JARVIS_MODEL_ROUTER_ENABLED").lower()
    return val not in {"false", "0", "no", "off"}


def normalize_tier(task: str | None) -> str:
    t = (task or "").strip().lower()
    return t if t in _VALID_TIERS else TIER_STANDARD


def resolve_model(task: str | None = None) -> str:
    """Return the model id for a task tier, honoring the precedence contract."""
    pinned = _env("JARVIS_BEDROCK_MODEL_ID")
    if pinned:
        return pinned
    if not router_enabled():
        return LEGACY_DEFAULT_MODEL_ID
    tier = normalize_tier(task)
    override = _env(_TIER_ENV[tier])
    if override:
        return override
    return DEFAULT_MODELS[tier]


def fallback_chain(task: str | None = None) -> list[str]:
    """Ordered models to attempt: resolved model, then one escalation tier up."""
    pinned = _env("JARVIS_BEDROCK_MODEL_ID")
    if pinned:
        return [pinned]
    if not router_enabled():
        return [LEGACY_DEFAULT_MODEL_ID]
    tier = normalize_tier(task)
    chain = [resolve_model(tier)]
    nxt = _ESCALATION.get(tier)
    if nxt:
        escalated = resolve_model(nxt)
        if escalated not in chain:
            chain.append(escalated)
    return chain
