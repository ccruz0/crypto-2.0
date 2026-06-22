"""Load LAB-only runtime secrets without exposing values in logs."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def _parse_env_lines(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key:
            out[key] = value
    return out


def load_lab_runtime_env(*, repo_root: Path | None = None, override_lab: bool = True) -> list[str]:
    """
    Load ``secrets/runtime.env`` then ``secrets/runtime.env.lab``.

    When ``override_lab`` is True (default), keys from ``runtime.env.lab`` replace
    earlier values so LAB flags are not overwritten by production-rendered runtime.env.
    """
    if repo_root is None:
        from app.services._paths import workspace_root

        repo_root = workspace_root()

    loaded: list[str] = []
    secrets_dir = repo_root / "secrets"
    for name, should_override in (("runtime.env", False), ("runtime.env.lab", override_lab)):
        path = secrets_dir / name
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            logger.debug("lab_secrets: skip unreadable %s: %s", path, exc)
            continue
        for key, value in _parse_env_lines(text).items():
            if should_override:
                os.environ[key] = value
            else:
                os.environ.setdefault(key, value)
        loaded.append(name)
    return loaded
