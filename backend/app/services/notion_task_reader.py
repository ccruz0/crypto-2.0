"""
Read-only Notion task reader for the Automated Trading Platform.

Allows OpenClaw and other agents to fetch pending tasks from the Notion
"AI Task System" database (NOTION_TASK_DB). Used for task intake only;
no status updates or writes in this module.

Environment variables (same as notion_tasks.py):
- NOTION_API_KEY: Notion integration token.
- NOTION_TASK_DB: Notion database ID for the "AI Task System" database.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Priority order for sorting (higher index = lower priority)
_PRIORITY_ORDER = ("critical", "high", "medium", "low")

# Ignore tasks with Priority Score below this unless no higher-priority tasks (idle)
PRIORITY_SCORE_LOW_THRESHOLD = 20

# Exact Notion Status/Select option names for pickup filter — must match schema exactly.
# Notion API is case-sensitive; lowercase variants cause 400 "select option not found".
# Normalization to internal form (planned, backlog, etc.) happens AFTER fetch in _parse_page.
NOTION_PICKABLE_STATUS_OPTIONS = (
    "Planned",
    "Backlog",
    "Ready for Investigation",
    "Blocked",
)
# Internal normalized status names (used for comparisons after parsing).
INTERNAL_PICKABLE_STATUSES = ("planned", "backlog", "ready-for-investigation", "blocked")


def _get_config() -> tuple[str, str]:
    """
    Read Notion API key and database ID.

    Priority:
    1) Process environment variables
    2) app.core.config.settings (loads from .env)
    """
    api_key = (os.environ.get("NOTION_API_KEY") or "").strip()
    database_id = (os.environ.get("NOTION_TASK_DB") or os.environ.get("NOTION_TASKS_DB") or "").strip()
    if api_key and database_id:
        return api_key, database_id
    try:
        from app.core.config import settings
    except Exception:
        return api_key, database_id
    if not api_key:
        api_key = (getattr(settings, "NOTION_API_KEY", None) or "").strip()
    if not database_id:
        database_id = (
            getattr(settings, "NOTION_TASK_DB", None) or getattr(settings, "NOTION_TASKS_DB", None) or ""
        ).strip()
    return api_key, database_id


def _extract_plain_text(prop_value: Any) -> str:
    """Extract plain text from a Notion property value.

    Handles select, multi_select, status, rich_text, title, and formula
    property types.  Returns empty string for unsupported or empty values.
    """
    if not prop_value:
        return ""
    if isinstance(prop_value, list):
        parts = []
        for item in prop_value:
            if isinstance(item, dict):
                plain = item.get("plain_text")
                if plain is not None:
                    parts.append(str(plain))
                else:
                    text_obj = item.get("text") or {}
                    parts.append(str(text_obj.get("content", "")) if isinstance(text_obj, dict) else str(text_obj))
        return "".join(parts).strip()
    if isinstance(prop_value, dict):
        select_obj = prop_value.get("select")
        if isinstance(select_obj, dict):
            return str(select_obj.get("name") or "").strip()

        status_obj = prop_value.get("status")
        if isinstance(status_obj, dict):
            return str(status_obj.get("name") or "").strip()

        multi = prop_value.get("multi_select")
        if isinstance(multi, list) and multi:
            names = [str(item.get("name") or "") for item in multi if isinstance(item, dict)]
            return ", ".join(n for n in names if n).strip()

        formula_obj = prop_value.get("formula")
        if isinstance(formula_obj, dict):
            for ftype in ("string", "number", "boolean"):
                fval = formula_obj.get(ftype)
                if fval is not None:
                    return str(fval).strip()

        rich = prop_value.get("rich_text") or prop_value.get("title")
        if isinstance(rich, list):
            return _extract_plain_text(rich)
        return str(prop_value.get("plain_text", ""))
    return str(prop_value)


def _extract_url(prop_value: Any) -> str:
    """Extract URL from a Notion url property value."""
    if not prop_value or not isinstance(prop_value, dict):
        return ""
    return (prop_value.get("url") or "").strip()


def _extract_bool_like(prop_value: Any) -> bool:
    """Extract bool flag from checkbox or text/select-like property."""
    if isinstance(prop_value, dict) and "checkbox" in prop_value:
        return bool(prop_value.get("checkbox"))
    text = _extract_plain_text(prop_value).strip().lower()
    return text in ("1", "true", "yes", "y", "approved", "allow", "allowed")


def _extract_priority_score(props: dict[str, Any]) -> int:
    """Extract Priority Score (0–100 number) from Notion props. Returns 0 if missing or invalid."""
    for name in ("Priority Score", "priority_score", "PriorityScore"):
        if name not in props:
            continue
        val = props.get(name)
        if val is None:
            continue
        if isinstance(val, dict) and "number" in val:
            try:
                n = val["number"]
                return max(0, min(100, int(n))) if n is not None else 0
            except (TypeError, ValueError):
                return 0
    return 0


def _normalize_status_from_notion(raw_status: str) -> str:
    """Map Notion Status (display or internal) to backend internal value (lowercase, hyphenated)."""
    from app.services.notion_tasks import notion_status_from_display
    return notion_status_from_display(raw_status or "")


def _normalize_execution_mode(raw: str) -> str:
    """Normalize execution_mode to 'normal' or 'strict'. Default 'normal' when absent or invalid."""
    v = (raw or "").strip().lower()
    if v == "strict":
        return "strict"
    return "normal"


def _extract_execution_mode_raw(props: dict[str, Any]) -> str:
    """Extract raw Execution Mode for debug logging. Returns repr of value or 'MISSING'."""
    for name in ("Execution Mode", "execution_mode", "ExecutionMode"):
        if name in props:
            val = props.get(name)
            if val is None:
                return f"{name}=None"
            if isinstance(val, dict):
                sel = val.get("select")
                if isinstance(sel, dict):
                    n = sel.get("name")
                    return f"{name}(select)={n!r}"
                st = val.get("status")
                if isinstance(st, dict):
                    n = st.get("name")
                    return f"{name}(status)={n!r}"
                rt = val.get("rich_text")
                if isinstance(rt, list) and rt:
                    return f"{name}(rich_text)={_extract_plain_text(rt)!r}"
                return f"{name}(dict)={list(val.keys())}"
            return f"{name}={val!r}"
    return "MISSING"


def _extract_execution_mode_from_props(props: dict[str, Any]) -> str:
    """Extract execution_mode from Notion props. Tries multiple property names and structures."""
    for name in ("Execution Mode", "execution_mode", "ExecutionMode"):
        if name not in props:
            continue
        val = props.get(name)
        if val is None:
            continue
        extracted = _extract_plain_text(val)
        if extracted:
            return _normalize_execution_mode(extracted)
    return "normal"


def _parse_page(page: dict[str, Any]) -> dict[str, Any]:
    """Parse a Notion page object into a normalized task dict."""
    props = page.get("properties") or {}
    def _prop_text(*names: str) -> str:
        for name in names:
            if name in props:
                value = _extract_plain_text(props.get(name))
                if value:
                    return value
        return ""

    raw_type_prop = props.get("Type")
    parsed_type = _extract_plain_text(raw_type_prop)
    notion_prop_type = raw_type_prop.get("type") if isinstance(raw_type_prop, dict) else type(raw_type_prop).__name__
    if raw_type_prop is not None:
        logger.info(
            "_parse_page: Type field — notion_prop_type=%s parsed=%r raw_keys=%s page_id=%s",
            notion_prop_type,
            parsed_type,
            list(raw_type_prop.keys()) if isinstance(raw_type_prop, dict) else "n/a",
            page.get("id", "")[:12],
        )

    # Task title: accept Task, Name, or Task Title (form-style)
    task_title = (
        _extract_plain_text(props.get("Task"))
        or _extract_plain_text(props.get("Name"))
        or _extract_plain_text(props.get("Task Title"))
    )
    # Main description: accept Details or Description (form-style)
    task_details = (
        _extract_plain_text(props.get("Details"))
        or _extract_plain_text(props.get("Description"))
    )

    raw_status = _extract_plain_text(props.get("Status"))
    normalized_status = _normalize_status_from_notion(raw_status) if raw_status else ""

    task = {
        "id": page.get("id", ""),
        "task": task_title,
        "project": _extract_plain_text(props.get("Project")),
        "type": parsed_type,
        "status": normalized_status or raw_status,
        "priority": _extract_plain_text(props.get("Priority")),
        "source": _extract_plain_text(props.get("Source")),
        "details": task_details,
        "github_link": _extract_url(props.get("GitHub Link")),
        # Versioning metadata
        "current_version": _prop_text("Current Version", "current_version"),
        "proposed_version": _prop_text("Proposed Version", "proposed_version"),
        "approved_version": _prop_text("Approved Version", "approved_version"),
        "released_version": _prop_text("Released Version", "released_version"),
        "version_status": _prop_text("Version Status", "version_status"),
        "change_summary": _prop_text("Change Summary", "change_summary"),
        # Extended task metadata
        "risk_level": _prop_text("Risk Level", "risk_level"),
        "repo": _prop_text("Repo", "repo"),
        "environment": _prop_text("Environment", "environment"),
        "openclaw_report_url": _prop_text("OpenClaw Report URL", "openclaw_report_url"),
        "cursor_patch_url": _prop_text("Cursor Patch URL", "cursor_patch_url"),
        "test_status": _prop_text("Test Status", "test_status"),
        "deploy_approval": _prop_text("Deploy Approval", "deploy_approval"),
        "final_result": _prop_text("Final Result", "final_result"),
        "revision_count": _prop_text("Revision Count", "revision_count"),
        "revision_reason": _prop_text("Revision Reason", "revision_reason"),
        "blocker_reason": _prop_text("Blocker Reason", "blocker_reason"),
        # Per-task OpenClaw approval gate (checkbox preferred, text/select fallback)
        "allow_openclaw": _extract_bool_like(
            props.get("Allow OpenClaw")
            or props.get("allow_openclaw")
            or props.get("AllowOpenClaw")
        ),
        # Strict execution mode: "normal" (default) or "strict" — blocks ready-for-patch until proof exists
        "execution_mode": _extract_execution_mode_from_props(props),
        # Priority Score: 0–100 number for scheduler ordering (optional property "Priority Score")
        "priority_score": _extract_priority_score(props),
        # Notion page metadata (for recovery / staleness checks)
        "last_edited_time": page.get("last_edited_time") or "",
        "created_time": page.get("created_time") or "",
    }
    # Debug: trace execution_mode from Notion through parse
    _raw_exec = _extract_execution_mode_raw(props)
    _norm_exec = task.get("execution_mode", "?")
    logger.info(
        "execution_mode_trace _parse_page page_id=%s raw_prop=%s normalized=%s",
        page.get("id", "")[:12],
        _raw_exec,
        _norm_exec,
    )
    if _raw_exec == "MISSING":
        _exec_keys = [k for k in props if "exec" in k.lower() or "mode" in k.lower()]
        logger.info(
            "execution_mode_trace _parse_page page_id=%s Execution Mode not found; "
            "props_with_exec_or_mode=%s all_prop_keys=%s",
            page.get("id", "")[:12],
            _exec_keys,
            list(props.keys())[:20],
        )
    if _norm_exec == "strict":
        logger.info("STRICT MODE DETECTED at _parse_page task_id=%s", page.get("id", "")[:12])
    return task


def get_notion_task_by_id(page_id: str) -> dict[str, Any] | None:
    """Fetch a single Notion task page by ID and return a parsed task dict.

    Returns ``None`` on missing config, network error, or non-200 response.
    Never raises.
    """
    page_id = (page_id or "").strip()
    if not page_id:
        return None
    api_key, _ = _get_config()
    if not api_key:
        logger.warning("get_notion_task_by_id skipped: NOTION_API_KEY not set")
        return None
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(f"{NOTION_API_BASE}/pages/{page_id}", headers=headers)
        if resp.status_code != 200:
            logger.warning("get_notion_task_by_id: HTTP %d for page_id=%s", resp.status_code, page_id)
            return None
        return _parse_page(resp.json())
    except Exception as exc:
        logger.warning("get_notion_task_by_id failed page_id=%s: %s", page_id, exc)
        return None


def get_pending_notion_tasks(
    *,
    project: Optional[str] = None,
    type_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Fetch tasks from the Notion "AI Task System" database where Status is one of:
    Planned, Backlog, Ready for Investigation, or Blocked.

    Uses NOTION_API_KEY and NOTION_TASK_DB from environment. On missing config,
    network failure, or API error, returns an empty list and logs; does not raise.

    Args:
        project: If set, only return tasks whose Project matches (case-insensitive substring).
        type_filter: If set, only return tasks whose Type matches (case-insensitive substring).

    Returns:
        List of normalized task dicts. Each dict has keys (all str): id, task,
        project, type, status, priority, source, details, github_link. Empty
        list on missing config, network failure, or API error (no exception raised).
    """
    api_key, database_id = _get_config()
    if not api_key:
        logger.warning("Notion task reader skipped: NOTION_API_KEY not set")
        return []
    if not database_id:
        logger.warning("Notion task reader skipped: NOTION_TASK_DB not set")
        return []

    # Use only exact valid Notion Status/Select option names. Lowercase causes 400 validation_error.
    status_options = list(NOTION_PICKABLE_STATUS_OPTIONS)

    logger.info(
        "notion_pickup_status_options options_queried=%s (exact Notion schema names only)",
        status_options,
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    logger.info(
        "notion_scan_started database_id=%s project=%r type_filter=%r",
        database_id[:8] + "…" if len(database_id) > 8 else database_id,
        project,
        type_filter,
    )

    def _query_pages(
        payload: dict[str, Any],
        client: httpx.Client,
        *,
        status_filter_keys: Optional[list[str]] = None,
    ) -> list[dict[str, Any]] | None:
        """Run a paginated Notion query.  Returns list of parsed pages, or None on HTTP error.

        If status_filter_keys is provided (e.g. ["status", "select"]), on 400 validation_error
        we try the next key (for Status property: Notion uses "status" type or "select" type).
        """
        filter_keys = status_filter_keys or [None]
        equals_val = ""
        if "filter" in payload:
            flt = payload["filter"]
            if isinstance(flt, dict) and flt.get("property") == "Status":
                equals_val = (flt.get("status") or flt.get("select") or {}).get("equals", "")

        for key_idx, filter_key in enumerate(filter_keys):
            work_payload = dict(payload)
            if filter_key and equals_val and "filter" in work_payload:
                work_payload["filter"] = {
                    "property": "Status",
                    filter_key: {"equals": equals_val},
                }

            pages = []
            cursor = None
            while True:
                if cursor:
                    work_payload["start_cursor"] = cursor
                else:
                    work_payload.pop("start_cursor", None)
                response = client.post(
                    f"{NOTION_API_BASE}/databases/{database_id}/query",
                    json=work_payload,
                    headers=headers,
                )
                if response.status_code != 200:
                    try:
                        err_body = response.text[:500]
                    except Exception:
                        err_body = ""
                    is_validation = "validation_error" in (err_body or "").lower()
                    if is_validation and key_idx + 1 < len(filter_keys):
                        logger.debug(
                            "Notion query 400 with filter key %r, trying next: %s",
                            filter_key, err_body[:200],
                        )
                        break
                    logger.warning(
                        "Notion query returned status=%d body=%s",
                        response.status_code,
                        err_body,
                    )
                    return None

                data = response.json()
                for page in data.get("results") or []:
                    pages.append(page)
                cursor = data.get("next_cursor")
                if not cursor or not data.get("has_more"):
                    return pages

    all_tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    import time
    max_attempts = 3
    last_error: Optional[str] = None
    for attempt in range(max_attempts):
        if attempt > 0:
            delay = min(2 ** attempt, 10)
            logger.info("notion_pickup_retry attempt=%s delay=%ss", attempt + 1, delay)
            time.sleep(delay)
        try:
            with httpx.Client(timeout=15.0) as client:
                raw_pages: list[dict[str, Any]] = []

                for status_variant in status_options:
                    # Status in Notion can be "status" type (native) or "select" type (legacy).
                    filter_payload = {
                        "filter": {"property": "Status", "select": {"equals": status_variant}},
                        "page_size": 100,
                    }
                    pages = _query_pages(
                        filter_payload, client,
                        status_filter_keys=["status", "select"],
                    )
                    if pages is not None:
                        for p in pages:
                            pid = (p.get("id") or "").strip()
                            if pid and pid not in seen_ids:
                                seen_ids.add(pid)
                                raw_pages.append(p)
                        logger.info(
                            "Notion query succeeded status_variant=%r pages=%d (total unique=%d)",
                            status_variant,
                            len(pages),
                            len(raw_pages),
                        )
                        if pages:
                            first_props = (pages[0].get("properties") or {}).get("Status") or {}
                            raw_status_val = (
                                (first_props.get("status") or first_props.get("select") or {})
                                .get("name", "")
                                if isinstance(first_props, dict)
                                else ""
                            )
                            logger.info(
                                "notion_pickup_debug first_page_status_raw=%r page_id=%s",
                                raw_status_val or "(empty)",
                                (pages[0].get("id") or "")[:12],
                            )
                    else:
                        logger.warning(
                            "Notion query failed for status_variant=%r (HTTP error or validation) — trying next variant",
                            status_variant,
                        )

                if not raw_pages:
                    logger.warning(
                        "Notion task read: no tasks found for any pickable status "
                        "database_id=%s status_options_tried=%s — check that tasks have Status "
                        "exactly one of: Planned, Backlog, Ready for Investigation, Blocked",
                        database_id[:8] + "…" if len(database_id) > 8 else database_id,
                        status_options,
                    )
                    return []

                for page in raw_pages:
                    parsed = _parse_page(page)
                    task_title = parsed.get("task") or "(untitled)"
                    if project and project.strip():
                        if project.strip().lower() not in (parsed.get("project") or "").lower():
                            logger.info(
                                "notion_pickup_task_rejected id=%s title=%r status=%r reason=project_mismatch "
                                "task_project=%r filter_project=%r",
                                parsed.get("id", "")[:12],
                                task_title[:50],
                                parsed.get("status"),
                                parsed.get("project"),
                                project,
                            )
                            continue
                    if type_filter and type_filter.strip():
                        if type_filter.strip().lower() not in (parsed.get("type") or "").lower():
                            logger.info(
                                "notion_pickup_task_rejected id=%s title=%r status=%r reason=type_mismatch "
                                "task_type=%r filter_type=%r",
                                parsed.get("id", "")[:12],
                                task_title[:50],
                                parsed.get("status"),
                                parsed.get("type"),
                                type_filter,
                            )
                            continue
                    logger.info(
                        "task_detected title=%r status=%r type=%r priority=%r",
                        task_title[:60], parsed.get("status"), parsed.get("type"), parsed.get("priority"),
                    )
                    all_tasks.append(parsed)

            # Debug: patch tasks (Type=Patch or title PATCH:) eligible for Cursor execution
            patch_candidates = [
                t for t in all_tasks
                if ((t.get("type") or "").strip().lower() == "patch")
                or ((t.get("task") or "").strip().startswith("PATCH:"))
            ]
            if patch_candidates:
                logger.info(
                    "patch_task_candidates count=%d ids=%s titles=%s",
                    len(patch_candidates),
                    [str(t.get("id", ""))[:12] for t in patch_candidates],
                    [str((t.get("task") or "")[:40]) for t in patch_candidates],
                )
            for t in patch_candidates:
                logger.info(
                    "patch_task_candidate id=%s title=%r type=%r status=%r source=%r",
                    str(t.get("id", ""))[:12],
                    (t.get("task") or "")[:50],
                    t.get("type"),
                    t.get("status"),
                    t.get("source"),
                )

            logger.info(
                "notion_tasks_found count=%d (after project/type filtering)",
                len(all_tasks),
            )
            return all_tasks
        except (httpx.TimeoutException, httpx.RequestError, Exception) as e:
            last_error = str(e)
            logger.warning("notion_pickup_retry attempt=%s error=%s", attempt + 1, last_error[:200])
            if attempt == max_attempts - 1:
                if isinstance(e, httpx.TimeoutException):
                    logger.error("Notion task read timed out (after %s attempts): %s", max_attempts, e)
                elif isinstance(e, httpx.RequestError):
                    logger.error("Notion task read request failed (after %s attempts): %s", max_attempts, e)
                else:
                    logger.error("Notion task read failed (after %s attempts): %s", max_attempts, e, exc_info=True)
                return []
    return []


def get_high_priority_pending_tasks(
    *,
    project: Optional[str] = None,
    type_filter: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    Fetch pending Notion tasks and return them ordered by priority:
    critical > high > medium > low. Same env and filtering as get_pending_notion_tasks.
    """
    tasks = get_pending_notion_tasks(project=project, type_filter=type_filter)
    if not tasks:
        logger.info(
            "get_high_priority_pending_tasks: no tasks project=%r type_filter=%r "
            "(get_pending_notion_tasks returned empty — check notion_pickup_status_variants and "
            "notion_pickup_task_rejected logs)",
            project,
            type_filter,
        )
        return []

    # Priority Score (0–100): prefer higher; default 0 when missing
    def priority_score_val(t: dict[str, Any]) -> int:
        return int(t.get("priority_score") or 0)

    # Low-priority filter: ignore tasks with priority_score < threshold unless system idle (no higher-priority tasks)
    high_enough = [t for t in tasks if priority_score_val(t) >= PRIORITY_SCORE_LOW_THRESHOLD]
    candidates = high_enough if high_enough else tasks

    # Sort by Priority Score DESC, then by text priority (critical > high > medium > low) as tiebreaker
    def text_priority_key(t: dict[str, Any]) -> int:
        p = (t.get("priority") or "medium").strip().lower()
        try:
            return _PRIORITY_ORDER.index(p)
        except ValueError:
            return _PRIORITY_ORDER.index("medium")

    tasks_sorted = sorted(
        candidates,
        key=lambda t: (-priority_score_val(t), text_priority_key(t)),
    )
    if tasks_sorted:
        top = tasks_sorted[0]
        logger.info(
            "scheduler_priority_selection task_id=%s title=%r priority_score=%d",
            (top.get("id") or "")[:12],
            (top.get("task") or "")[:50],
            priority_score_val(top),
        )
    return tasks_sorted


def get_tasks_by_status(
    statuses: list[str],
    *,
    max_results: int = 10,
) -> list[dict[str, Any]]:
    """Fetch tasks whose Notion Status matches any of *statuses*.

    Unlike ``get_pending_notion_tasks`` (which only queries intake statuses),
    this function accepts an arbitrary status list so the scheduler can pick
    up tasks in mid-lifecycle statuses like ``ready-for-patch``.

    Returns at most *max_results* parsed task dicts.  Never raises.
    """
    if not statuses:
        return []

    api_key, database_id = _get_config()
    if not api_key or not database_id:
        logger.warning("get_tasks_by_status skipped: missing Notion config")
        return []

    try:
        from app.services.notion_tasks import notion_status_to_display
    except (ImportError, AttributeError):
        _FALLBACK_DISPLAY = {
            "planned": "Planned", "backlog": "Backlog", "ready-for-investigation": "Ready for Investigation",
            "investigation-complete": "Investigation Complete", "ready-for-patch": "Ready for Patch",
            "patching": "Patching", "testing": "Testing", "release-candidate-ready": "Release Candidate Ready",
            "ready-for-deploy": "Ready for Deploy", "awaiting-deploy-approval": "Awaiting Deploy Approval",
            "deploying": "Deploying", "done": "Done",
        }
        def notion_status_to_display(s: str) -> str:
            return _FALLBACK_DISPLAY.get((s or "").strip().lower(), (s or "").strip())

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    all_tasks: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    def _query_by_status_filter(display_status: str, page_size: int) -> list[dict[str, Any]]:
        """Query by Status; try status filter first (Notion native), then select (legacy)."""
        for filter_key in ("status", "select"):
            payload = {
                "filter": {"property": "Status", filter_key: {"equals": display_status}},
                "page_size": page_size,
            }
            try:
                resp = client.post(
                    f"{NOTION_API_BASE}/databases/{database_id}/query",
                    json=payload,
                    headers=headers,
                )
            except Exception as req_err:
                logger.debug("get_tasks_by_status: request failed filter_key=%r: %s", filter_key, req_err)
                continue
            if resp.status_code == 200:
                return [page for page in (resp.json().get("results") or [])]
            if resp.status_code == 400 and "validation_error" in (resp.text or "").lower():
                logger.debug("get_tasks_by_status: 400 with filter_key=%r, trying next", filter_key)
                continue
            logger.debug(
                "get_tasks_by_status: HTTP %d for status=%r filter_key=%r",
                resp.status_code, display_status, filter_key,
            )
        return []

    try:
        with httpx.Client(timeout=15.0) as client:
            for status in statuses:
                if len(all_tasks) >= max_results:
                    break
                display_status = notion_status_to_display(status) or status
                pages = _query_by_status_filter(
                    display_status,
                    min(max_results - len(all_tasks), 100),
                )
                for page in pages:
                    pid = (page.get("id") or "").strip()
                    if pid and pid not in seen_ids:
                        seen_ids.add(pid)
                        all_tasks.append(_parse_page(page))
                    if len(all_tasks) >= max_results:
                        break
    except Exception as exc:
        logger.warning("get_tasks_by_status failed: %s", exc)

    logger.info("get_tasks_by_status statuses=%s found=%d", statuses, len(all_tasks))
    return all_tasks


def get_raw_status_distribution(max_pages: int = 100) -> dict[str, Any]:
    """
    Diagnostic: query Notion database with NO status filter, return distribution of
    raw Status values. Use to verify exact casing/format Notion stores (e.g. "planned" vs "Planned").
    """
    api_key, database_id = _get_config()
    if not api_key or not database_id:
        return {"ok": False, "error": "missing config", "by_status": {}}
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    by_status: dict[str, list[str]] = {}
    total_fetched = 0
    try:
        with httpx.Client(timeout=15.0) as client:
            payload: dict[str, Any] = {"page_size": min(max_pages, 100)}
            cursor = None
            while total_fetched < max_pages:
                if cursor:
                    payload["start_cursor"] = cursor
                else:
                    payload.pop("start_cursor", None)
                resp = client.post(
                    f"{NOTION_API_BASE}/databases/{database_id}/query",
                    json=payload,
                    headers=headers,
                )
                if resp.status_code != 200:
                    return {"ok": False, "error": f"HTTP {resp.status_code}", "by_status": dict(by_status)}
                data = resp.json()
                results = data.get("results") or []
                total_fetched += len(results)
                for page in results:
                    props = (page.get("properties") or {}).get("Status") or {}
                    inner = (props.get("status") or props.get("select") or {}) if isinstance(props, dict) else {}
                    raw = inner.get("name", "") if isinstance(inner, dict) else ""
                    pid = (page.get("id") or "").strip()
                    if raw not in by_status:
                        by_status[raw] = []
                    by_status[raw].append(pid[:12] + "…" if len(pid) > 12 else pid)
                cursor = data.get("next_cursor")
                if not cursor or not data.get("has_more"):
                    break
    except Exception as e:
        return {"ok": False, "error": str(e), "by_status": dict(by_status)}
    return {"ok": True, "by_status": {k: v for k, v in by_status.items()}, "pickable": list(NOTION_PICKABLE_STATUS_OPTIONS)}


def test_notion_task_scan(
    *,
    project: Optional[str] = None,
    type_filter: Optional[str] = None,
) -> dict[str, Any]:
    """
    Diagnostic function: query the Notion database and return a structured
    report of what the scanner sees.  Safe to call from a shell or API route.

    Returns a dict with:
      ok: bool
      config: {api_key_set, database_id_prefix}
      tasks_found: int
      tasks: [{id, task, status, priority, project, type}, ...]
      error: str | None
    """
    api_key, database_id = _get_config()
    report: dict[str, Any] = {
        "ok": False,
        "config": {
            "api_key_set": bool(api_key),
            "database_id_prefix": (database_id[:8] + "…") if len(database_id) > 8 else database_id or "(empty)",
        },
        "tasks_found": 0,
        "tasks": [],
        "error": None,
    }
    if not api_key:
        report["error"] = "NOTION_API_KEY not set"
        return report
    if not database_id:
        report["error"] = "NOTION_TASK_DB not set"
        return report

    try:
        tasks = get_pending_notion_tasks(project=project, type_filter=type_filter)
        report["ok"] = True
        report["tasks_found"] = len(tasks)
        report["tasks"] = [
            {
                "id": t.get("id", ""),
                "task": t.get("task", ""),
                "status": t.get("status", ""),
                "priority": t.get("priority", ""),
                "project": t.get("project", ""),
                "type": t.get("type", ""),
            }
            for t in tasks
        ]
    except Exception as e:
        report["error"] = str(e)

    return report
