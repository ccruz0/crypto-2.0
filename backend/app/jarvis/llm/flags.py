"""Fail-closed feature flags for Bedrock-routed JARVIS investigations.

Both flags default to FALSE. They are read from the environment directly (rather
than added to the shared Settings class) so this capability is purely additive
and isolated. Nothing here enables any write/execute path.
"""

from __future__ import annotations

import os

_TRUTHY = {"1", "true", "yes", "on"}


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def bedrock_enabled() -> bool:
    """True only when JARVIS_BEDROCK_ENABLED is explicitly truthy. Default False."""
    return _flag("JARVIS_BEDROCK_ENABLED")


def disk_investigator_enabled() -> bool:
    """True only when JARVIS_DISK_INVESTIGATOR_ENABLED is explicitly truthy. Default False."""
    return _flag("JARVIS_DISK_INVESTIGATOR_ENABLED")
