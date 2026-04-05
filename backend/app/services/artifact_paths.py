"""Writable per-task artifact directories (host-side persistence).

Complements ``_paths.py`` (bug-investigations, cursor-handoffs). Used for normalized
task JSON and OpenClaw prompt hints so outputs are not tied to OpenClaw container paths.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def get_base_artifact_dir() -> Path:
    """Prefer ``<workspace_root>/docs/agents``; fall back to ``/tmp/agent-artifacts``."""
    try:
        from app.services._paths import workspace_root

        root = workspace_root()
        candidate = root / "docs" / "agents"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe_paths"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError as e:
            logger.warning("artifact_paths: docs/agents not writable (%s), using /tmp/agent-artifacts", e)
    except Exception as e:
        logger.warning("artifact_paths: workspace_root failed (%s), using /tmp/agent-artifacts", e)
    fb = Path(os.environ.get("AGENT_ARTIFACTS_BASE", "/tmp/agent-artifacts"))
    fb.mkdir(parents=True, exist_ok=True)
    return fb


def get_task_dir(task_id: str) -> Path:
    """Return ``.../tasks/{task_id}/`` (created)."""
    tid = (task_id or "").strip()
    if not tid:
        tid = "unknown"
    base = get_base_artifact_dir()
    path = base / "tasks" / tid
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_cursor_handoff_candidates(task_id: str) -> list[Path]:
    """Ordered search paths for ``cursor-handoff-{task_id}.md`` (per-task tree first)."""
    tid = (task_id or "").strip()
    if not tid:
        return []
    try:
        from app.services._paths import get_writable_cursor_handoffs_dir

        return [
            get_task_dir(tid) / f"cursor-handoff-{tid}.md",
            get_writable_cursor_handoffs_dir() / f"cursor-handoff-{tid}.md",
        ]
    except Exception:
        return []


def resolve_cursor_handoff_path_for_read(task_id: str) -> Path | None:
    """Return first existing handoff file path, or None."""
    for p in list_cursor_handoff_candidates(task_id):
        try:
            if p.is_file():
                return p
        except OSError:
            continue
    return None


def get_normalized_tasks_dir() -> Path:
    """Directory for ``task-{id}.normalized.json`` (under ``docs/agents/tasks`` or fallback)."""
    try:
        from app.services._paths import workspace_root

        root = workspace_root()
        candidate = root / "docs" / "agents" / "tasks"
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / ".write_probe_norm"
            probe.write_text("", encoding="utf-8")
            probe.unlink(missing_ok=True)
            return candidate
        except OSError as e:
            logger.warning("artifact_paths: normalized tasks dir not writable (%s)", e)
    except Exception as e:
        logger.debug("artifact_paths: normalized dir workspace failed %s", e)
    fb = Path(os.environ.get("AGENT_TASKS_DIR", "/tmp/agent-tasks"))
    fb.mkdir(parents=True, exist_ok=True)
    return fb
