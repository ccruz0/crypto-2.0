"""Forbidden path validation for Phase 5 patch apply."""

from __future__ import annotations

import fnmatch
import re
from typing import Any

# Default forbidden path patterns (relative to repo root).
DEFAULT_FORBIDDEN_PATTERNS: tuple[str, ...] = (
    "secrets/*",
    "secrets/**",
    ".env",
    ".env.*",
    "runtime.env",
    "**/.env",
    "**/.env.*",
    "**/runtime.env",
    "**/*private*key*",
    "**/*.pem",
    "**/*.key",
    "frontend/src/app/openclaw/**",
)

DEPLOYMENT_PATTERNS: tuple[str, ...] = (
    "scripts/deploy/**",
    "deploy/**",
    ".github/workflows/deploy*.yml",
)

# Trading execution paths blocked unless task explicitly allows.
TRADING_PATH_PATTERNS: tuple[str, ...] = (
    "backend/app/trading/**",
    "backend/app/services/trading/**",
    "backend/app/execution/**",
    "scripts/trading/**",
)


def _normalize_path(path: str) -> str:
    p = (path or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p.lstrip("/")


def _matches_pattern(path: str, pattern: str) -> bool:
    norm = _normalize_path(path)
    pat = _normalize_path(pattern)
    if fnmatch.fnmatch(norm, pat):
        return True
    if fnmatch.fnmatch(norm, pat.rstrip("/**") + "/**"):
        return True
    # Also check basename for simple patterns like .env
    basename = norm.rsplit("/", 1)[-1]
    if fnmatch.fnmatch(basename, pat):
        return True
    return False


def check_forbidden_paths(
    changed_files: list[str],
    *,
    allow_trading: bool = False,
    allow_deployment: bool = False,
    extra_forbidden: list[str] | None = None,
) -> dict[str, Any]:
    """Return validation result; blocked=True if any forbidden path touched."""
    patterns = list(DEFAULT_FORBIDDEN_PATTERNS)
    if not allow_deployment:
        patterns.extend(DEPLOYMENT_PATTERNS)
    if not allow_trading:
        patterns.extend(TRADING_PATH_PATTERNS)
    if extra_forbidden:
        patterns.extend(extra_forbidden)

    blocked: list[str] = []
    for fpath in changed_files:
        norm = _normalize_path(fpath)
        for pattern in patterns:
            if _matches_pattern(norm, pattern):
                blocked.append(norm)
                break

    return {
        "passed": len(blocked) == 0,
        "blocked_paths": sorted(set(blocked)),
        "checked_files": [_normalize_path(f) for f in changed_files],
        "allow_trading": allow_trading,
        "allow_deployment": allow_deployment,
    }


def task_allows_trading(objective: str, plan: dict[str, Any] | None = None) -> bool:
    text = (objective or "").lower()
    if re.search(r"\ballow\s+trading\b|\btrading\s+approved\b|\bexplicit.*trading\b", text):
        return True
    phase5 = (plan or {}).get("phase5") or {}
    return bool(phase5.get("allow_trading"))


def task_allows_deployment(objective: str, plan: dict[str, Any] | None = None) -> bool:
    text = (objective or "").lower()
    if re.search(r"\ballow\s+deploy\b|\bdeployment\s+approved\b|\bexplicit.*deploy\b", text):
        return True
    phase5 = (plan or {}).get("phase5") or {}
    return bool(phase5.get("allow_deployment"))
