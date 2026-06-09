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


def _explicit_patch_request(blob: str) -> bool:
    return any(
        k in blob
        for k in (
            "code patch",
            "apply patch",
            "create patch",
            "patch handoff",
            "cursor handoff",
            "cursor bridge",
            "implementation handoff",
            "open pr",
            "code change",
            "modify code",
            "fix and patch",
        )
    )


def _safe_readonly_investigation_report_blob(blob: str, explicit_patch: bool) -> bool:
    """Title/details ask for investigate + report + read-only with no explicit patch request."""
    if explicit_patch:
        return False
    bl = blob.lower()
    has_report = "produce report" in bl or "produce a report" in bl
    has_investigate = (
        "investigate" in bl
        or "investigation" in bl
        or bl.startswith("investigate ")
    )
    has_readonly = "read-only" in bl or "read only" in bl or "readonly" in bl
    return bool(has_report and has_investigate and has_readonly)


def classify_code_fix_task(task: dict[str, Any] | None) -> tuple[bool, str]:
    """Classify whether task should be treated as code-fix for patch/Cursor Bridge gating.

    Returns (is_code_fix, reason) for logs and tests.
    """
    if not task:
        return False, "no_task"
    task_obj = task.get("task") if isinstance(task.get("task"), dict) else task
    raw = str(task_obj.get("type") or task.get("type") or "").strip().lower()
    title = str(task_obj.get("task") or task.get("task") or "").strip().lower()
    details = str(task_obj.get("details") or task.get("details") or "").strip().lower()
    blob = f"{title} {details}"
    is_full_audit = (
        ("audit atp codebase" in blob)
        or ("full-system audit" in blob)
        or ("full system audit" in blob)
        or ("against documentation and business rules" in blob)
        or (
            "audit" in blob
            and "atp" in blob
            and ("documentation" in blob or "business rules" in blob or "codebase" in blob)
        )
    )
    explicit_patch = _explicit_patch_request(blob)
    if is_full_audit and not explicit_patch:
        return False, "excluded_full_audit_no_explicit_patch"

    # Any Notion type: read-only investigation + report deliverable (mis-typed as Bug still excluded).
    if _safe_readonly_investigation_report_blob(blob, explicit_patch):
        return False, "excluded_safe_readonly_investigation_report"

    # Investigation types often produce markdown reports only (no repo patch).
    if raw in ("investigation", "architecture investigation") and not explicit_patch:
        report_only_markers = (
            "produce report",
            "produce a report",
            "write report",
            "report only",
            "read-only",
            "read only",
            "analysis only",
            "investigate and report",
            "investigation report",
            "document findings",
            "audit report",
            "consistency report",
            "health report",
            "produce an investigation",
            "investigation output",
            "analysis and produce",
        )
        if any(m in blob for m in report_only_markers):
            return False, "excluded_investigation_report_deliverable"

    if raw not in CODE_FIX_TASK_TYPES:
        return False, f"not_code_fix_type:{raw or 'empty'}"

    return True, f"code_fix_type:{raw}"


def is_code_fix_task(task: dict[str, Any] | None) -> bool:
    """True if the task type implies code changes and requires Cursor Bridge before deploy."""
    return classify_code_fix_task(task)[0]


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
    from app.services.artifact_paths import resolve_cursor_handoff_path_for_read

    return resolve_cursor_handoff_path_for_read(task_id) is not None


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
    is_cf, cf_detail = classify_code_fix_task(task)
    task_obj = task.get("task") if isinstance(task.get("task"), dict) else task
    notion_type = str(task_obj.get("type") or task.get("type") or "").strip()
    title_preview = str(task_obj.get("task") or task.get("task") or "").strip()[:120]
    logger.info(
        "patch_proof.classify task_id=%s is_code_fix=%s detail=%s notion_type=%r title_preview=%r",
        (task_id or "").strip() or "?",
        is_cf,
        cf_detail,
        notion_type,
        title_preview,
    )
    if not is_cf:
        return False, "not_code_fix"

    proof_ok, proof_reason = has_patch_proof(task_id, task)
    if proof_ok:
        return False, f"patch_proof_exists ({proof_reason})"

    # Code-fix task with no patch proof — block deploy
    handoff_ok = handoff_exists_for_task(task_id)
    if handoff_ok:
        return True, "code_fix_handoff_exists_no_patch"
    return True, "code_fix_no_handoff_no_patch"
