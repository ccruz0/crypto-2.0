"""
Patch proof gate for code-fix tasks.

Ensures code-fix tasks cannot advance to ready-for-deploy without evidence that
Cursor Bridge has applied code changes. Investigation alone is not implementation.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Task types that imply code changes and require Cursor Bridge before deploy
CODE_FIX_TASK_TYPES = (
    "bug",
    "bugfix",
    "bug fix",
    "investigation",
    "architecture investigation",
)

# Task types that may skip Cursor Bridge (doc-only, ops-only, monitoring triage)
DOC_OPS_TASK_TYPES = (
    "documentation",
    "monitoring",
    "triage",
    "ops",
)


def _workspace_root() -> Path:
    from app.services._paths import workspace_root
    return workspace_root()


def is_code_fix_task(task: dict[str, Any] | None) -> bool:
    """True if the task type implies code changes and requires Cursor Bridge before deploy."""
    if not task:
        return False
    task_obj = task.get("task") if isinstance(task.get("task"), dict) else task
    raw = str(task_obj.get("type") or task.get("type") or "").strip().lower()
    return raw in CODE_FIX_TASK_TYPES


def is_doc_or_ops_task(task: dict[str, Any] | None) -> bool:
    """True if the task type implies doc-only or ops-only (may skip Cursor Bridge)."""
    if not task:
        return False
    task_obj = task.get("task") if isinstance(task.get("task"), dict) else task
    raw = str(task_obj.get("type") or task.get("type") or "").strip().lower()
    return raw in DOC_OPS_TASK_TYPES


def handoff_exists_for_task(task_id: str) -> bool:
    """True if the Cursor handoff file exists for this task."""
    task_id = (task_id or "").strip()
    if not task_id:
        return False
    handoff_path = _workspace_root() / "docs" / "agents" / "cursor-handoffs" / f"cursor-handoff-{task_id}.md"
    return handoff_path.exists()


def has_patch_proof(task_id: str, task: dict[str, Any] | None = None) -> tuple[bool, str]:
    """
    Check if there is objective evidence that code was applied for this task.

    Evidence (any of):
    - docs/agents/patches/{task_id}.diff exists and is non-empty
    - cursor_patch_url in Notion task metadata
    - cursor_bridge_ingest_done or cursor_bridge_diff_captured in activity log for this task

    Returns (has_proof, reason) for logging.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return False, "empty task_id"

    # 1. Diff file exists
    root = _workspace_root()
    diff_path = root / "docs" / "agents" / "patches" / f"{task_id}.diff"
    if diff_path.exists():
        try:
            size = diff_path.stat().st_size
            if size > 0:
                return True, f"diff_exists path={diff_path} size={size}"
        except OSError:
            pass

    # 2. cursor_patch_url in Notion metadata
    if task:
        patch_url = (task.get("cursor_patch_url") or "").strip()
        if patch_url:
            return True, f"cursor_patch_url={patch_url[:80]}"

    # 3. Activity log: cursor_bridge_ingest_done or cursor_bridge_diff_captured
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        for ev in get_recent_agent_events(limit=500):
            if ev.get("task_id") != task_id:
                continue
            et = ev.get("event_type") or ""
            if et in ("cursor_bridge_ingest_done", "cursor_bridge_diff_captured", "cursor_bridge_auto_success"):
                return True, f"activity_log event={et}"
    except Exception as e:
        logger.debug("patch_proof: activity log check failed: %s", e)

    return False, "no_patch_proof"


def cursor_bridge_required_for_task(task: dict[str, Any], task_id: str) -> tuple[bool, str]:
    """
    True if this task requires Cursor Bridge to run before deploy approval.

    Returns (required, reason):
    - (True, "code_fix_no_patch_proof") when code-fix task with no patch proof (handoff may or may not exist)
    - (False, "not_code_fix") when doc/ops task
    - (False, "patch_proof_exists") when proof already exists
    """
    if not is_code_fix_task(task):
        return False, "not_code_fix"

    proof_ok, proof_reason = has_patch_proof(task_id, task)
    if proof_ok:
        return False, f"patch_proof_exists ({proof_reason})"

    # Code-fix task with no patch proof — block deploy
    handoff_ok = handoff_exists_for_task(task_id)
    if handoff_ok:
        return True, "code_fix_handoff_exists_no_patch"
    return True, "code_fix_no_handoff_no_patch"
