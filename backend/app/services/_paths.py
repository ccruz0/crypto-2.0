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

Cursor handoffs: ``get_writable_cursor_handoffs_dir()`` matches the same pattern (repo
``docs/agents/cursor-handoffs`` or ``AGENT_CURSOR_HANDOFFS_DIR`` / ``/tmp/agent-cursor-handoffs``).
Required when ``./docs`` is bind-mounted from the host with root-only permissions.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_bug_investigations_dir: Optional[Path] = None
_cursor_handoffs_dir: Optional[Path] = None


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


def get_writable_cursor_handoffs_dir() -> Path:
    """Return a writable directory for Cursor bridge handoff markdown files.

    Tries ``<workspace_root>/docs/agents/cursor-handoffs`` first (same layout as dev).
    If that path is not writable (common in production: ``./docs`` bind-mounted from
    the host with root-owned files), falls back to ``AGENT_CURSOR_HANDOFFS_DIR`` or
    ``/tmp/agent-cursor-handoffs``.

    Must be used by ``save_cursor_handoff``, ``_cursor_handoff_path``, and any
    code that checks for ``cursor-handoff-{task_id}.md`` so lookup always matches writes.
    """
    global _cursor_handoffs_dir
    if _cursor_handoffs_dir is not None:
        return _cursor_handoffs_dir

    root = workspace_root()
    candidate = root / "docs" / "agents" / "cursor-handoffs"
    explicit = (os.environ.get("AGENT_CURSOR_HANDOFFS_DIR") or "").strip()
    fallback = Path(explicit) if explicit else Path("/tmp/agent-cursor-handoffs")

    def _log_resolution(chosen: Path, *, used_fallback: bool, err: Exception | None = None) -> None:
        exists = chosen.is_dir()
        writable = False
        try:
            if exists:
                probe = chosen / ".write_probe"
                probe.write_text("", encoding="utf-8")
                probe.unlink(missing_ok=True)
                writable = True
        except OSError:
            writable = False
        logger.info(
            "cursor_handoffs_dir: effective=%s exists=%s writable=%s workspace_candidate=%s "
            "used_fallback=%s err=%s",
            chosen,
            exists,
            writable,
            candidate,
            used_fallback,
            err,
        )

    try:
        candidate.mkdir(parents=True, exist_ok=True)
        probe = candidate / ".write_probe"
        probe.write_text("", encoding="utf-8")
        probe.unlink(missing_ok=True)
        _cursor_handoffs_dir = candidate
        _log_resolution(_cursor_handoffs_dir, used_fallback=False)
        return _cursor_handoffs_dir
    except (OSError, PermissionError) as e:
        logger.warning(
            "cursor_handoffs_dir: repo path %s not writable (%s), using fallback %s",
            candidate,
            e,
            fallback,
        )
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            probe = fallback / ".write_probe"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _cursor_handoffs_dir = fallback
            _log_resolution(_cursor_handoffs_dir, used_fallback=True, err=e)
            return _cursor_handoffs_dir
        except (OSError, PermissionError) as e2:
            logger.error(
                "cursor_handoffs_dir: fallback %s also not writable: %s",
                fallback,
                e2,
            )
            _log_resolution(fallback, used_fallback=True, err=e2)
            raise


def get_writable_dir_for_subdir(save_subdir: str) -> Path:
    """
    Return a writable directory for artifact subdirs. Single canonical path resolution.
    - bug-investigations: uses get_writable_bug_investigations_dir (repo or fallback)
    - cursor-handoffs: uses get_writable_cursor_handoffs_dir (repo or fallback)
    - telegram-alerts, execution-state, etc.: try repo first; fallback to AGENT_ARTIFACTS_DIR/subdir
    """
    if save_subdir == "docs/agents/bug-investigations":
        return get_writable_bug_investigations_dir()
    if save_subdir == "docs/agents/cursor-handoffs":
        return get_writable_cursor_handoffs_dir()
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
