"""Environment configuration for Jarvis Phase 5 change execution."""

from __future__ import annotations

import os


def _bool_env(name: str, default: bool = False) -> bool:
    raw = (os.environ.get(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def jarvis_patch_apply_enabled() -> bool:
    """Allow sandbox patch apply after Gate 1 approval. Default: disabled."""
    return _bool_env("JARVIS_PATCH_APPLY_ENABLED", default=False)


def jarvis_pr_creation_enabled() -> bool:
    """Allow GitHub PR creation after Gate 2 approval. Default: disabled."""
    return _bool_env("JARVIS_PR_CREATION_ENABLED", default=False)


def jarvis_github_write_enabled() -> bool:
    """Allow write-capable git/gh commands. Default: disabled."""
    return _bool_env("JARVIS_GITHUB_WRITE_ENABLED", default=False)


def jarvis_require_double_approval() -> bool:
    """Require both Gate 1 and Gate 2 approvals. Default: enabled."""
    return _bool_env("JARVIS_REQUIRE_DOUBLE_APPROVAL", default=True)


def jarvis_sandbox_timeout_sec() -> int:
    raw = (os.environ.get("JARVIS_SANDBOX_TIMEOUT_SEC") or "300").strip()
    try:
        return max(30, min(int(raw), 900))
    except ValueError:
        return 300


def jarvis_test_timeout_sec() -> int:
    raw = (os.environ.get("JARVIS_TEST_TIMEOUT_SEC") or "120").strip()
    try:
        return max(10, min(int(raw), 600))
    except ValueError:
        return 120


def phase5_safety_status() -> dict[str, bool]:
    """Current Phase 5 safety flag snapshot (no secrets)."""
    return {
        "patch_apply_enabled": jarvis_patch_apply_enabled(),
        "pr_creation_enabled": jarvis_pr_creation_enabled(),
        "github_write_enabled": jarvis_github_write_enabled(),
        "double_approval_required": jarvis_require_double_approval(),
    }
