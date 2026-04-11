"""Resolve current Jarvis deployment environment (dev / lab / prod)."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

KNOWN_JARVIS_ENVS = frozenset({"dev", "lab", "prod"})


def get_jarvis_env() -> str:
    """
    Read ``JARVIS_ENV`` (case-insensitive). Defaults to ``dev`` when unset.
    Unknown values log a warning and fall back to ``dev``.
    """
    raw = (os.environ.get("JARVIS_ENV") or "").strip().lower()
    if not raw:
        return "dev"
    if raw not in KNOWN_JARVIS_ENVS:
        logger.warning(
            "jarvis.runtime_env.invalid JARVIS_ENV=%r; falling back to dev",
            os.environ.get("JARVIS_ENV"),
        )
        return "dev"
    return raw
