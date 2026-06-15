"""Resolve backend build fingerprint (commit SHA, build time) for health headers."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

_GIT_SHA_FILE = Path("/app/.git_sha")
_BUILD_TIME_FILE = Path("/app/.build_time")
_UNKNOWN = "unknown"


def _read_fingerprint_file(path: Path) -> str | None:
    if not path.is_file():
        return None
    value = path.read_text(encoding="utf-8").strip()
    if not value or value == _UNKNOWN:
        return None
    return value


@lru_cache(maxsize=1)
def resolve_git_sha() -> str:
    """Return deployed git SHA from env or baked /app/.git_sha file."""
    env_value = (os.getenv("ATP_GIT_SHA") or os.getenv("GIT_SHA") or "").strip()
    if env_value and env_value != _UNKNOWN:
        return env_value
    file_value = _read_fingerprint_file(_GIT_SHA_FILE)
    if file_value:
        return file_value
    return _UNKNOWN


@lru_cache(maxsize=1)
def resolve_build_time() -> str:
    """Return image build time from env or baked /app/.build_time file."""
    env_value = (os.getenv("ATP_BUILD_TIME") or os.getenv("BUILD_TIME") or "").strip()
    if env_value and env_value != _UNKNOWN:
        return env_value
    file_value = _read_fingerprint_file(_BUILD_TIME_FILE)
    if file_value:
        return file_value
    return _UNKNOWN
