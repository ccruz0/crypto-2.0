"""Environment configuration for the Jarvis Self-Healing Advisor (Phase 7)."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def self_healing_enabled() -> bool:
    """Allow self-healing recommendations to be generated. Default: disabled."""
    return _bool_env("JARVIS_SELF_HEALING_ENABLED", default=False)


def self_healing_acw_threshold() -> float:
    """Confidence (0-100) at or above which a recommendation becomes ACW-ready."""
    raw = (os.environ.get("JARVIS_SELF_HEALING_ACW_THRESHOLD") or "70").strip()
    try:
        return max(0.0, min(float(raw), 100.0))
    except ValueError:
        return 70.0


def self_healing_safety_status() -> dict[str, bool | float]:
    """Current self-healing safety flag snapshot (no secrets)."""
    return {
        "self_healing_enabled": self_healing_enabled(),
        "acw_threshold": self_healing_acw_threshold(),
        # Self-healing can never execute fixes; these are always read-only.
        "auto_execution": False,
        "auto_merge": False,
        "auto_deploy": False,
        "human_approval_required": True,
    }
