"""Shared workspace root resolution for artifact writes.

Every module that writes files under ``docs/``, ``logs/``, or any other
project-relative directory **must** use ``workspace_root()`` from this
module instead of its own ``_repo_root()`` helper.

Resolution order:
1. ``ATP_WORKSPACE_ROOT`` environment variable (explicit override for Docker/prod)
2. Nearest ancestor containing ``.git`` (local development)
3. Nearest ancestor at depth 3 or 2 containing a ``docs/`` directory
4. ``parents[2]`` of this file — safe fallback that resolves to ``/app``
   in the standard Docker layout ``/app/app/services/_paths.py``

The resolved path is cached after first call.

Bug investigations: ``get_writable_bug_investigations_dir()`` returns a path
that is writable (repo docs/ or ``AGENT_BUG_INVESTIGATIONS_DIR`` / ``/tmp/agent-bug-investigations``).
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_bug_investigations_dir: Optional[Path] = None


@lru_cache(maxsize=1)
def workspace_root() -> Path:
    """Return the writable project/workspace root directory."""

    env_root = (os.environ.get("ATP_WORKSPACE_ROOT") or "").strip()
    if env_root:
        resolved = Path(env_root).resolve()
        logger.info("workspace_root: using ATP_WORKSPACE_ROOT=%s", resolved)
        return resolved

    here = Path(__file__).resolve()

    for ancestor in here.parents:
        if (ancestor / ".git").is_dir():
            logger.info("workspace_root: found .git at %s", ancestor)
            return ancestor

    for idx in (3, 2):
        if idx < len(here.parents):
            candidate = here.parents[idx]
            if (candidate / "docs").is_dir():
                logger.info(
                    "workspace_root: found docs/ at parents[%d]=%s", idx, candidate,
                )
                return candidate

    fallback = here.parents[min(2, len(here.parents) - 1)]
    logger.info("workspace_root: using fallback parents[2]=%s", fallback)
    return fallback


def get_writable_bug_investigations_dir() -> Path:
    """Return a writable directory for bug-investigation notes (repo or fallback)."""
    global _bug_investigations_dir
    if _bug_investigations_dir is not None:
        return _bug_investigations_dir
    root = workspace_root()
    candidate = root / "docs" / "agents" / "bug-investigations"
    fallback = Path(os.environ.get("AGENT_BUG_INVESTIGATIONS_DIR", "/tmp/agent-bug-investigations"))
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        _bug_investigations_dir = candidate
        return _bug_investigations_dir
    except (OSError, PermissionError) as e:
        logger.warning(
            "bug-investigations: repo path %s not writable (%s), using fallback %s",
            candidate, e, fallback,
        )
        fallback.mkdir(parents=True, exist_ok=True)
        _bug_investigations_dir = fallback
        return _bug_investigations_dir


def get_writable_dir_for_subdir(save_subdir: str) -> Path:
    """
    Return a writable directory for artifact subdirs. Single canonical path resolution.
    - bug-investigations: uses get_writable_bug_investigations_dir (repo or fallback)
    - telegram-alerts, execution-state, etc.: try repo first; fallback to AGENT_ARTIFACTS_DIR/subdir
    """
    if save_subdir == "docs/agents/bug-investigations":
        return get_writable_bug_investigations_dir()
    root = workspace_root()
    candidate = root / save_subdir
    base_fallback = Path(os.environ.get("AGENT_ARTIFACTS_DIR", "/tmp/agent-artifacts"))
    fallback = base_fallback / Path(save_subdir).name
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return candidate
    except (OSError, PermissionError) as e:
        logger.warning(
            "artifacts: repo path %s not writable (%s), using fallback %s",
            candidate, e, fallback,
        )
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
