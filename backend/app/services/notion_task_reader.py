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


def _get_config() -> tuple[str, str]:
    """
    Read Notion API key and database ID.

    Priority:
    1) Process environment variables
    2) app.core.config.settings (loads from .env)
    """
    api_key = (os.environ.get("NOTION_API_KEY") or "").strip()
    database_id = (os.environ.get("NOTION_TASK_DB") or "").strip()
    if api_key and database_id:
        return api_key, database_id
    try:
        from app.core.config import settings
    except Exception:
        return api_key, database_id
    if not api_key:
        api_key = (getattr(settings, "NOTION_API_KEY", None) or "").strip()
    if not database_id:
        database_id = (getattr(settings, "NOTION_TASK_DB", None) or "").strip()
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


def _normalize_status_from_notion(raw_status: str) -> str:
    """Map Notion Status (display or internal) to backend internal value (lowercase, hyphenated)."""
    from app.services.notion_tasks import notion_status_from_display
    return notion_status_from_display(raw_status or "")


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
        # Notion page metadata (for recovery / staleness checks)
        "last_edited_time": page.get("last_edited_time") or "",
    }
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
    Fetch tasks from the Notion "AI Task System" database where Status = "planned".

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

    # Status in Notion is a Select property: use only select filter with display names.
    try:
        from app.services.notion_tasks import notion_status_to_display
    except (ImportError, AttributeError):
        _FALLBACK_DISPLAY = {
            "planned": "Planned", "backlog": "Backlog", "ready-for-investigation": "Ready for Investigation",
            "investigation-complete": "Investigation Complete", "ready-for-patch": "Ready for Patch",
            "patching": "Patching", "testing": "Testing", "deploying": "Deploying", "done": "Done",
        }
        def notion_status_to_display(s: str) -> str:
            return _FALLBACK_DISPLAY.get((s or "").strip().lower(), (s or "").strip())
    _INTERNAL_PICKABLE = ("planned", "backlog", "ready-for-investigation")
    _STATUS_VARIANTS = [
        notion_status_to_display(s) for s in _INTERNAL_PICKABLE
    ] + ["Planned", "Backlog", "Ready for Investigation"]  # fallback display names
    _STATUS_VARIANTS = list(dict.fromkeys(_STATUS_VARIANTS))  # dedupe

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

    try:
        with httpx.Client(timeout=15.0) as client:
            raw_pages: list[dict[str, Any]] | None = None

            for status_variant in _STATUS_VARIANTS:
                # Status in Notion can be "status" type (native) or "select" type (legacy).
                # Try "status" first, fall back to "select" on 400 validation_error.
                filter_payload = {
                    "filter": {"property": "Status", "select": {"equals": status_variant}},
                    "page_size": 100,
                }
                raw_pages = _query_pages(
                    filter_payload, client,
                    status_filter_keys=["status", "select"],
                )
                if raw_pages is not None:
                    logger.info(
                        "Notion query succeeded status_variant=%r raw_pages=%d",
                        status_variant,
                        len(raw_pages),
                    )
                    break
                logger.debug(
                    "Notion query failed for status_variant=%r, trying next",
                    status_variant,
                )

            if raw_pages is None:
                logger.error(
                    "Notion task read failed: all filter combinations returned errors "
                    "database_id=%s",
                    database_id[:8] + "…" if len(database_id) > 8 else database_id,
                )
                return []

            for page in raw_pages:
                parsed = _parse_page(page)
                task_title = parsed.get("task") or "(untitled)"
                if project and project.strip():
                    if project.strip().lower() not in (parsed.get("project") or "").lower():
                        logger.debug("task_skipped title=%r reason=project_mismatch", task_title)
                        continue
                if type_filter and type_filter.strip():
                    if type_filter.strip().lower() not in (parsed.get("type") or "").lower():
                        logger.debug("task_skipped title=%r reason=type_mismatch", task_title)
                        continue
                logger.info("task_detected title=%r status=%r priority=%r", task_title, parsed.get("status"), parsed.get("priority"))
                all_tasks.append(parsed)

        logger.info(
            "notion_tasks_found count=%d (after project/type filtering)",
            len(all_tasks),
        )
        return all_tasks

    except httpx.TimeoutException as e:
        logger.error("Notion task read timed out: %s", e)
        return []
    except httpx.RequestError as e:
        logger.error("Notion task read request failed: %s", e)
        return []
    except Exception as e:
        logger.error("Notion task read failed: %s", e, exc_info=True)
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
        return []

    def priority_key(t: dict[str, Any]) -> int:
        p = (t.get("priority") or "medium").strip().lower()
        try:
            return _PRIORITY_ORDER.index(p)
        except ValueError:
            return _PRIORITY_ORDER.index("medium")

    tasks_sorted = sorted(tasks, key=priority_key)
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
            "patching": "Patching", "testing": "Testing", "deploying": "Deploying", "done": "Done",
        }
        def notion_status_to_display(s: str) -> str:
            return _FALLBACK_DISPLAY.get((s or "").strip().lower(), (s or "").strip())

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    all_tasks: list[dict[str, Any]] = []

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
                    all_tasks.append(_parse_page(page))
                    if len(all_tasks) >= max_results:
                        break
                if all_tasks:
                    break
    except Exception as exc:
        logger.warning("get_tasks_by_status failed: %s", exc)

    logger.info("get_tasks_by_status statuses=%s found=%d", statuses, len(all_tasks))
    return all_tasks


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
