"""
Task decomposition for complex investigations.

When a task is repeatedly stuck or inherently complex, decompose it into smaller
child tasks instead of endless re-investigation. Enforces:
- max 2 automatic re-investigate attempts before decompose/block
- max decomposition depth = 2
- max 5 child tasks per parent
- no duplicate decomposition for same parent
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger(__name__)

# Max automatic re-investigate before decompose or block
MAX_AUTO_REINVESTIGATE = 2

# Decomposition limits
MAX_DECOMPOSITION_DEPTH = 2
MAX_CHILD_TASKS_PER_PARENT = 5

# Keywords that suggest a complex / multi-phase task
COMPLEXITY_KEYWORDS = (
    "end-to-end",
    "full flow",
    "full pipeline",
    "verify.*patch.*deploy",
    "investigate.*patch.*verify",
    "investigate.*patch",
    "root cause and fix",
    "root cause and patch",
    "complete flow",
    "entire flow",
    "full verification",
    "multi-step",
    "multiple phases",
    "multiple systems",
    "several modules",
    "several components",
)

# Detail prefix for subtask linkage (parsed when checking parent-child)
SUBTASK_DETAIL_PREFIX = "[ATP_SUBTASK]"
SUBTASK_PARENT_RE = re.compile(r"parent_task_id:\s*([\w\-]+)", re.I)
SUBTASK_INDEX_RE = re.compile(r"subtask_index:\s*(\d+)", re.I)
SUBTASK_TOTAL_RE = re.compile(r"subtask_total:\s*(\d+)", re.I)


def _extract_parent_task_id(details: str) -> str | None:
    """Extract parent_task_id from task details if present."""
    if not details or SUBTASK_DETAIL_PREFIX not in details:
        return None
    m = SUBTASK_PARENT_RE.search(details)
    return m.group(1).strip() if m else None


def get_parent_task_id(task: dict[str, Any]) -> str | None:
    """Return parent_task_id if task is a child, else None."""
    details = (task.get("details") or "").strip()
    return _extract_parent_task_id(details)


def is_child_task(task: dict[str, Any]) -> bool:
    """True if task has parent_task_id in details."""
    return get_parent_task_id(task) is not None


def _is_complex_by_keywords(text: str) -> bool:
    """True if text matches complexity keywords (multi-phase, end-to-end, etc.)."""
    if not text:
        return False
    lower = text.lower()
    for kw in COMPLEXITY_KEYWORDS:
        if "*" in kw or "." in kw:
            try:
                if re.search(kw, lower):
                    return True
            except re.error:
                if kw in lower:
                    return True
        elif kw in lower:
            return True
    return False


def should_decompose_task(
    task: dict[str, Any],
    retry_count: int,
    *,
    decomposition_depth: int = 0,
    already_decomposed: bool = False,
) -> bool:
    """
    True if task should be decomposed instead of retried.

    Triggers:
    - retry_count >= MAX_AUTO_REINVESTIGATE (hit retry limit)
    - task title/details match complexity keywords
    - decomposition_depth < MAX_DECOMPOSITION_DEPTH
    - not already decomposed for this parent
    - not already a child task (no nested decomposition beyond depth 2)
    """
    if not task:
        return False
    if already_decomposed:
        return False
    if decomposition_depth >= MAX_DECOMPOSITION_DEPTH:
        return False
    if is_child_task(task):
        return False  # Child tasks don't get decomposed further at depth 1

    # Decompose when: hit retry limit (stuck after 2 retries) OR complex from start
    hit_retry_limit = retry_count >= MAX_AUTO_REINVESTIGATE
    title = (task.get("task") or "").strip()
    details = (task.get("details") or "").strip()
    combined = f"{title} {details}"
    is_complex = _is_complex_by_keywords(combined)

    if hit_retry_limit:
        return True
    if is_complex and retry_count >= 1:
        return True
    return False


def _default_subtasks_for_title(title: str, details: str) -> list[dict[str, Any]]:
    """
    Generate 2-5 child task specs from parent title/details.
    Conservative defaults for common patterns.
    """
    combined = (title + " " + details).lower()
    specs: list[dict[str, Any]] = []

    if "verify" in combined and ("patch" in combined or "deploy" in combined):
        specs = [
            {"scope": "Verify patch entry point and validation logic", "index": 1},
            {"scope": "Verify post-patch validation and tests", "index": 2},
            {"scope": "Verify deploy trigger conditions", "index": 3},
            {"scope": "Verify final result reconciliation", "index": 4},
        ]
    elif "full flow" in combined or "end-to-end" in combined:
        specs = [
            {"scope": "Investigate and document root cause", "index": 1},
            {"scope": "Implement fix / patch", "index": 2},
            {"scope": "Verify fix in isolation", "index": 3},
            {"scope": "Verify end-to-end flow", "index": 4},
        ]
    elif "root cause" in combined:
        specs = [
            {"scope": "Investigate and isolate root cause", "index": 1},
            {"scope": "Design and implement fix", "index": 2},
            {"scope": "Verify fix addresses root cause", "index": 3},
        ]
    else:
        # Generic split
        specs = [
            {"scope": "Part 1: Initial investigation and scope", "index": 1},
            {"scope": "Part 2: Implementation", "index": 2},
            {"scope": "Part 3: Verification", "index": 3},
        ]

    # Cap at MAX_CHILD_TASKS_PER_PARENT
    return specs[:MAX_CHILD_TASKS_PER_PARENT]


def _find_existing_active_subtasks_for_parent(parent_id: str) -> list[dict[str, Any]]:
    """
    Return non-terminal child tasks in Notion that reference *parent_id* in [ATP_SUBTASK] details.

    Survives backend restarts (unlike in-memory _decomposed_parents) so we do not create
    duplicate subtask rows for the same unresolved parent.
    """
    pid = (parent_id or "").strip()
    if len(pid) < 8:
        return []
    try:
        from app.services.notion_tasks import (
            TERMINAL_STATUSES,
            _get_config,
            _notion_query_pages_details_contains,
        )
        from app.services.notion_task_reader import _parse_page
    except ImportError:
        return []

    api_key, database_id = _get_config()
    if not api_key or not database_id:
        return []

    needle = f"parent_task_id: {pid}"
    pages = _notion_query_pages_details_contains(database_id, api_key, needle)
    out: list[dict[str, Any]] = []
    for page in pages:
        try:
            task = _parse_page(page)
        except Exception:
            continue
        details = str(task.get("details") or "")
        if SUBTASK_DETAIL_PREFIX not in details:
            continue
        if needle.lower() not in details.lower():
            continue
        st = str(task.get("status") or "").strip().lower()
        if st in TERMINAL_STATUSES:
            continue
        out.append(task)
    return out


def decompose_task(parent_task: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Create child task specs from parent. Does NOT persist to Notion; caller does that.

    Returns list of child specs: [{title, details, scope, index, total}, ...]
    """
    parent_id = (parent_task.get("id") or "").strip()
    title = (parent_task.get("task") or parent_task.get("title") or "(untitled)").strip()
    details = (parent_task.get("details") or "").strip()
    project = (parent_task.get("project") or "Operations").strip()
    task_type = (parent_task.get("type") or "Investigation").strip()

    subtask_specs = _default_subtasks_for_title(title, details)
    total = len(subtask_specs)

    children: list[dict[str, Any]] = []
    for spec in subtask_specs:
        scope = spec.get("scope", "Subtask")
        idx = spec.get("index", len(children) + 1)
        child_title = f"{title[:50]} (subtask {idx}/{total})"
        child_details_block = (
            f"{SUBTASK_DETAIL_PREFIX}\n"
            f"parent_task_id: {parent_id}\n"
            f"subtask_index: {idx}\n"
            f"subtask_total: {total}\n"
            f"subtask_scope: {scope}\n"
            "---\n"
            f"{scope}\n\n"
            f"Parent: {title[:100]}"
        )
        children.append({
            "title": child_title,
            "details": child_details_block,
            "scope": scope,
            "subtask_index": idx,
            "subtask_total": total,
            "project": project,
            "type": task_type,
            "parent_task_id": parent_id,
        })

    return children


def execute_decomposition(parent_task: dict[str, Any]) -> dict[str, Any]:
    """
    Create child tasks in Notion, move parent to waiting-on-subtasks.
    Returns {ok, parent_id, child_ids, error}.
    """
    parent_id = (parent_task.get("id") or "").strip()
    if not parent_id:
        return {"ok": False, "parent_id": "", "child_ids": [], "error": "missing parent id"}

    existing_children = _find_existing_active_subtasks_for_parent(parent_id)
    if existing_children:
        child_ids = [str(t.get("id") or "").strip() for t in existing_children if t.get("id")]
        child_ids = [c for c in child_ids if c]
        if child_ids:
            logger.info(
                "task_decomposition_skipped_duplicate_children parent_id=%s active_children=%d",
                parent_id[:12],
                len(child_ids),
            )
            return {
                "ok": True,
                "parent_id": parent_id,
                "child_ids": child_ids,
                "child_count": len(child_ids),
                "dedup_skipped": True,
            }
        # Notion matched Details but parsed tasks lack ids — do not create a second batch of children.
        logger.warning(
            "task_decomposition_skipped_duplicate_children_no_ids parent_id=%s matched=%d",
            parent_id[:12],
            len(existing_children),
        )
        return {
            "ok": False,
            "parent_id": parent_id,
            "child_ids": [],
            "error": "active subtasks found in Notion but page ids missing",
        }

    children_specs = decompose_task(parent_task)
    if not children_specs:
        return {"ok": False, "parent_id": parent_id, "child_ids": [], "error": "no child specs"}

    try:
        from app.services.notion_tasks import (
            create_notion_task,
            TASK_STATUS_READY_FOR_INVESTIGATION,
            TASK_STATUS_WAITING_ON_SUBTASKS,
            update_notion_task_status,
            update_notion_task_metadata,
        )
    except ImportError as e:
        logger.warning("execute_decomposition: notion_tasks import failed %s", e)
        return {"ok": False, "parent_id": parent_id, "child_ids": [], "error": str(e)}

    child_ids: list[str] = []
    project = (parent_task.get("project") or "Operations").strip()
    task_type = (parent_task.get("type") or "Investigation").strip()

    for spec in children_specs:
        created = create_notion_task(
            title=spec["title"],
            project=project,
            type=task_type,
            details=spec["details"],
            status=TASK_STATUS_READY_FOR_INVESTIGATION,
            source="openclaw",
        )
        if created and created.get("id"):
            child_ids.append(created["id"])
            logger.info(
                "task_decomposition created_child parent_id=%s child_id=%s scope=%s",
                parent_id[:12], created["id"][:12], spec.get("scope", "")[:40],
            )

    if not child_ids:
        return {"ok": False, "parent_id": parent_id, "child_ids": [], "error": "no children created"}

    # Move parent to waiting-on-subtasks
    comment = (
        f"Decomposed into {len(child_ids)} subtasks (retry limit reached). "
        f"Children: {', '.join(c[:12] for c in child_ids)}. "
        "Parent will resume when all children complete."
    )
    ok = update_notion_task_status(
        parent_id,
        TASK_STATUS_WAITING_ON_SUBTASKS,
        append_comment=comment,
    )
    if ok:
        update_notion_task_metadata(parent_id, {"blocker_reason": f"Waiting on {len(child_ids)} subtasks"[:500]})
    else:
        logger.warning("execute_decomposition: parent status update failed parent_id=%s", parent_id[:12])

    return {
        "ok": bool(child_ids),
        "parent_id": parent_id,
        "child_ids": child_ids,
        "child_count": len(child_ids),
    }
