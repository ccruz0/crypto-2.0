"""Environment configuration for Jarvis Phase 4B patch proposals."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def jarvis_4b_proposals_enabled() -> bool:
    """Allow Phase 4B proposal eligibility and future patch proposal workflow. Default: disabled."""
    return _bool_env("JARVIS_4B_PROPOSALS_ENABLED", default=False)


def jarvis_4b_min_confidence() -> float:
    raw = (os.environ.get("JARVIS_4B_MIN_CONFIDENCE") or "50").strip()
    try:
        return max(0.0, min(float(raw), 100.0))
    except ValueError:
        return 50.0


def phase4b_safety_status() -> dict[str, bool | float]:
    """Current Phase 4B safety flag snapshot (no secrets)."""
    return {
        "phase4b_proposals_enabled": jarvis_4b_proposals_enabled(),
        "min_confidence": jarvis_4b_min_confidence(),
    }
