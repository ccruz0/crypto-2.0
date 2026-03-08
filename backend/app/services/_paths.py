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
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


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
