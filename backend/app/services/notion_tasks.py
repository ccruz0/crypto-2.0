"""
Notion task integration for the Automated Trading Platform.

Creates tasks in a Notion database ("AI Task System") for use by:
- Trading bot (e.g. when alerts fail or anomalies are detected)
- Monitoring scripts (e.g. health check failures, sync issues)
- OpenClaw agents (e.g. self-improving system creating follow-up tasks)

Environment variables:
- NOTION_API_KEY: Notion integration token (required).
- NOTION_TASK_DB: Notion database ID for the "AI Task System" database (required).
- NOTION_TASK_COOLDOWN_SECONDS: Deduplication window in seconds; tasks with the same
  (title, project, type, details) hash created within this window are skipped (default: 600).
- SERVICE_NAME: Service name for system context (default: "unknown-service").
- APP_ENV: Environment for system context (default: "unknown-environment").
"""

from __future__ import annotations

import hashlib
import logging
import os
import socket
import threading
import time
from datetime import datetime, timezone
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

NOTION_API_BASE = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"

# Default values for new tasks
DEFAULT_STATUS = "planned"
DEFAULT_SOURCE = "openclaw"

# ---------------------------------------------------------------------------
# Extended task lifecycle statuses
# ---------------------------------------------------------------------------

TASK_STATUS_BACKLOG = "backlog"
TASK_STATUS_READY_FOR_INVESTIGATION = "ready-for-investigation"
TASK_STATUS_INVESTIGATING = "investigating"
TASK_STATUS_INVESTIGATION_COMPLETE = "investigation-complete"
TASK_STATUS_READY_FOR_PATCH = "ready-for-patch"
TASK_STATUS_PATCHING = "patching"
TASK_STATUS_TESTING = "testing"
TASK_STATUS_AWAITING_DEPLOY_APPROVAL = "awaiting-deploy-approval"
TASK_STATUS_DEPLOYING = "deploying"
TASK_STATUS_DONE = "done"
TASK_STATUS_REJECTED = "rejected"
TASK_STATUS_BLOCKED = "blocked"

# Legacy statuses kept for backward compatibility
TASK_STATUS_PLANNED = "planned"
TASK_STATUS_IN_PROGRESS = "in-progress"
TASK_STATUS_DEPLOYED = "deployed"

# All valid statuses (extended + legacy)
ALLOWED_TASK_STATUSES = (
    TASK_STATUS_BACKLOG,
    TASK_STATUS_READY_FOR_INVESTIGATION,
    TASK_STATUS_INVESTIGATING,
    TASK_STATUS_INVESTIGATION_COMPLETE,
    TASK_STATUS_READY_FOR_PATCH,
    TASK_STATUS_PATCHING,
    TASK_STATUS_TESTING,
    TASK_STATUS_AWAITING_DEPLOY_APPROVAL,
    TASK_STATUS_DEPLOYING,
    TASK_STATUS_DONE,
    TASK_STATUS_REJECTED,
    TASK_STATUS_BLOCKED,
    # Legacy
    TASK_STATUS_PLANNED,
    TASK_STATUS_IN_PROGRESS,
    TASK_STATUS_DEPLOYED,
)

# Terminal statuses (cannot advance further)
TERMINAL_STATUSES = (TASK_STATUS_DONE, TASK_STATUS_DEPLOYED, TASK_STATUS_REJECTED)

# Extended lifecycle: ordered forward transitions
EXTENDED_LIFECYCLE_TRANSITIONS: dict[str, str] = {
    "backlog": "ready-for-investigation",
    "ready-for-investigation": "investigating",
    "investigating": "investigation-complete",
    "investigation-complete": "ready-for-patch",
    "ready-for-patch": "patching",
    "patching": "testing",
    "testing": "awaiting-deploy-approval",
    "awaiting-deploy-approval": "deploying",
    "deploying": "done",
}

# Legacy lifecycle (preserved for backward compat)
LEGACY_LIFECYCLE_TRANSITIONS: dict[str, str] = {
    "planned": "in-progress",
    "in-progress": "testing",
    "testing": "deployed",
}

# Map legacy status names to their extended equivalents
LEGACY_STATUS_ALIASES: dict[str, str] = {
    "planned": "backlog",
    "in-progress": "investigating",
    "deployed": "done",
}

# ---------------------------------------------------------------------------
# Task metadata fields (extended — best-effort; optional in Notion DB schema)
# ---------------------------------------------------------------------------

TASK_METADATA_PROPERTY_MAP: dict[str, str] = {
    "risk_level": "Risk Level",
    "repo": "Repo",
    "environment": "Environment",
    "openclaw_report_url": "OpenClaw Report URL",
    "cursor_patch_url": "Cursor Patch URL",
    "test_status": "Test Status",
    "deploy_approval": "Deploy Approval",
    "final_result": "Final Result",
}

# Versioning metadata fields (best-effort; optional in Notion DB schema)
VERSION_STATUS_VALUES = ("proposed", "approved", "released", "rejected")
VERSION_PROPERTY_MAP: dict[str, str] = {
    "current_version": "Current Version",
    "proposed_version": "Proposed Version",
    "approved_version": "Approved Version",
    "released_version": "Released Version",
    "version_status": "Version Status",
    "change_summary": "Change Summary",
}

# Deduplication: hash -> last creation timestamp (monotonic)
_dedup_cache: dict[str, float] = {}
_dedup_lock = threading.Lock()

DEFAULT_COOLDOWN_SECONDS = 600


def _get_cooldown_seconds() -> int:
    """Read cooldown from NOTION_TASK_COOLDOWN_SECONDS; default 600 (10 minutes)."""
    raw = (os.environ.get("NOTION_TASK_COOLDOWN_SECONDS") or "").strip()
    if not raw:
        return DEFAULT_COOLDOWN_SECONDS
    try:
        value = int(raw)
        return max(0, value)
    except ValueError:
        return DEFAULT_COOLDOWN_SECONDS


def _task_dedup_hash(title: str, project: str, type: str, details: str) -> str:
    """Compute a stable hash for (title, project, type, details) for deduplication."""
    blob = f"{title}|{project}|{type}|{details}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _dedup_prune_and_check(key: str, cooldown_sec: int) -> bool:
    """
    Prune expired entries, then return True if key is still within cooldown (duplicate).
    Caller must hold _dedup_lock.
    """
    now = time.monotonic()
    expired = [k for k, ts in _dedup_cache.items() if (now - ts) > cooldown_sec]
    for k in expired:
        del _dedup_cache[k]
    if key in _dedup_cache:
        return True
    return False


def _dedup_record(key: str) -> None:
    """Record that a task with this hash was just created. Caller must hold _dedup_lock."""
    _dedup_cache[key] = time.monotonic()


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


def _get_service_name() -> str:
    """Read SERVICE_NAME from environment; default 'unknown-service'."""
    value = (os.environ.get("SERVICE_NAME") or "").strip()
    return value if value else "unknown-service"


def _get_app_env() -> str:
    """Read APP_ENV from environment; default 'unknown-environment'."""
    value = (os.environ.get("APP_ENV") or "").strip()
    return value if value else "unknown-environment"


def _get_hostname() -> str:
    """Get hostname from Python runtime."""
    try:
        return socket.gethostname() or "unknown-host"
    except Exception:
        return "unknown-host"


def _build_system_context_block() -> str:
    """
    Build the 'System Context' block appended to task details.
    Uses SERVICE_NAME, APP_ENV from env (with defaults) and hostname from runtime.
    """
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    service = _get_service_name()
    environment = _get_app_env()
    host = _get_hostname()
    return (
        "System Context\n\n"
        f"Timestamp: {timestamp}\n"
        f"Service: {service}\n"
        f"Environment: {environment}\n"
        f"Host: {host}"
    )


def _rich_text(content: str) -> list[dict[str, Any]]:
    """Build a Notion rich_text value (plain text)."""
    if not content:
        return []
    return [
        {
            "type": "text",
            "text": {"content": content[:2000]},  # Notion text block limit
        }
    ]


def _title(content: str) -> list[dict[str, Any]]:
    """Build a Notion title value."""
    return [
        {
            "type": "text",
            "text": {"content": (content or "Untitled")[:2000]},
        }
    ]


def _append_page_comment(page_id: str, comment: str, headers: dict[str, str]) -> bool:
    """Best-effort paragraph append helper; never raises."""
    normalized_page_id = (page_id or "").strip()
    text = (comment or "").strip()
    if not normalized_page_id or not text:
        return False
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
    content = f"[{timestamp}] {text}"
    block_payload: dict[str, Any] = {
        "children": [
            {
                "object": "block",
                "type": "paragraph",
                "paragraph": {"rich_text": _rich_text(content)},
            }
        ]
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            r = client.patch(
                f"{NOTION_API_BASE}/blocks/{normalized_page_id}/children",
                json=block_payload,
                headers=headers,
            )
        return r.status_code == 200
    except Exception:
        return False


# Priority inference: keyword overrides (case-insensitive) take precedence, then task_type, then default.
_PRIORITY_CRITICAL_KEYWORDS = (
    "exchange error",
    "order sync failure",
    "critical",
    "database down",
    "container unhealthy",
    "api failure",
)
_PRIORITY_HIGH_KEYWORDS = (
    "duplicate signal",
    "timeout",
    "telegram failure",
    "degraded",
    "latency",
)
_TYPE_TO_PRIORITY: dict[str, str] = {
    "monitoring": "high",
    "infrastructure": "high",
    "bug": "high",
    "automation": "medium",
    "strategy": "medium",
    "improvement": "low",
}


def _infer_priority(
    task_type: str | None,
    title: str | None,
    details: str | None,
) -> str:
    """
    Infer task priority from type and text (title + details).
    Keyword overrides (critical / high) are checked first, then task_type mapping, then default 'medium'.
    All matching is case-insensitive.
    """
    combined = f"{(title or '')} {(details or '')}".lower()

    for phrase in _PRIORITY_CRITICAL_KEYWORDS:
        if phrase in combined:
            return "critical"
    for phrase in _PRIORITY_HIGH_KEYWORDS:
        if phrase in combined:
            return "high"

    if task_type:
        normalized_type = task_type.strip().lower()
        if normalized_type in _TYPE_TO_PRIORITY:
            return _TYPE_TO_PRIORITY[normalized_type]

    return "medium"


def create_notion_task(
    title: str,
    project: str,
    type: str,
    priority: Optional[str] = None,
    details: str = "",
    github_link: Optional[str] = None,
    *,
    status: str = DEFAULT_STATUS,
    source: str = DEFAULT_SOURCE,
    version_metadata: dict[str, Any] | None = None,
) -> Optional[dict[str, Any]]:
    """
    Create a new task page in the Notion "AI Task System" database.

    Args:
        title: Task title (maps to "Task" in Notion).
        project: Project name (maps to "Project").
        type: Task type (maps to "Type").
        priority: Priority (maps to "Priority"). If None or empty, inferred from type/title/details.
        details: Optional description/details (maps to "Details").
        github_link: Optional URL (maps to "GitHub Link").
        status: Status; default "planned".
        source: Source of the task; default "openclaw".

    Returns:
        The Notion page object as a dict if successful, None otherwise.
        Callers can use the returned dict to get "id", "url", etc.

    Deduplication:
        Before creating, a hash of (title, project, type, details) is checked against
        recently created tasks (in-memory, last NOTION_TASK_COOLDOWN_SECONDS). If the
        same task was created within that window, creation is skipped and None is returned.

    Environment:
        NOTION_API_KEY: Notion integration token.
        NOTION_TASK_DB: Notion database ID (AI Task System).
        NOTION_TASK_COOLDOWN_SECONDS: Deduplication window in seconds (default 600).

    Raises:
        No exceptions; errors are logged and None is returned so callers
        (trading bot, monitoring, OpenClaw) can continue without failing.
    """
    api_key, database_id = _get_config()
    if not api_key:
        logger.warning("Notion integration skipped: NOTION_API_KEY not set")
        return None
    if not database_id:
        logger.warning("Notion integration skipped: NOTION_TASK_DB not set")
        return None

    cooldown_sec = _get_cooldown_seconds()
    dedup_key = _task_dedup_hash(title, project, type, details or "")
    with _dedup_lock:
        if _dedup_prune_and_check(dedup_key, cooldown_sec):
            logger.info(
                "Notion task skipped (duplicate within cooldown window) title=%r project=%r type=%r",
                title,
                project,
                type,
            )
            return None

    # Resolve priority: use caller value if provided, otherwise infer and log.
    if priority and priority.strip():
        resolved_priority = priority.strip()
    else:
        resolved_priority = _infer_priority(type, title, details)
        logger.info(
            "Inferred Notion task priority=%s title=%r type=%r",
            resolved_priority,
            title,
            type,
        )

    # Append system context to details for the Notion page only (dedup uses original details).
    context_block = _build_system_context_block()
    suffix = "\n\n" + context_block
    caller_details = (details or "").strip()
    if not caller_details:
        enriched_details = context_block
    else:
        enriched_details = caller_details + suffix
    # Notion rich_text content limit 2000; keep full context, truncate caller details if needed.
    if len(enriched_details) > 2000:
        max_caller_len = 2000 - len(suffix) - 3  # leave room for "..."
        enriched_details = (caller_details[:max_caller_len].rstrip() + "..." + suffix)

    # Property keys must match the Notion database schema.
    # If your database uses Select type for Project/Type/Priority/Status/Source,
    # use {"select": {"name": "Option Name"}} instead of rich_text for those keys.
    properties: dict[str, Any] = {
        "Task": {"title": _title(title)},
        "Project": {"rich_text": _rich_text(project)},
        "Type": {"rich_text": _rich_text(type)},
        "Priority": {"rich_text": _rich_text(resolved_priority)},
        "Status": {"rich_text": _rich_text(status)},
        "Source": {"rich_text": _rich_text(source)},
        "Details": {"rich_text": _rich_text(enriched_details)},
    }

    if github_link and github_link.strip():
        properties["GitHub Link"] = {"url": github_link.strip()}

    payload: dict[str, Any] = {
        "parent": {"database_id": database_id, "type": "database_id"},
        "properties": properties,
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.post(
                f"{NOTION_API_BASE}/pages",
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException as e:
        logger.exception("Notion API request timed out: %s", e)
        return None
    except httpx.RequestError as e:
        logger.exception("Notion API request failed: %s", e)
        return None

    if response.status_code == 200:
        data = response.json()
        with _dedup_lock:
            _dedup_record(dedup_key)
        logger.info(
            "Notion task created: id=%s title=%r (details enriched with system context)",
            data.get("id", ""),
            title,
        )
        # Best-effort: write optional versioning fields when schema supports them.
        if version_metadata:
            page_id = str(data.get("id") or "").strip()
            if page_id:
                update_notion_task_version_metadata(
                    page_id=page_id,
                    metadata=version_metadata,
                )
        return data

    # Log error with body for debugging (avoid logging full token)
    try:
        err_body = response.text
    except Exception:
        err_body = ""
    logger.error(
        "Notion API error: status=%d body=%s",
        response.status_code,
        err_body[:500] if err_body else "",
    )
    return None


# ---------------------------------------------------------------------------
# Convenience wrappers
# ---------------------------------------------------------------------------


def create_incident_task(
    title: str,
    details: str = "",
    github_link: Optional[str] = None,
    source: str = "monitoring",
) -> Optional[dict[str, Any]]:
    """
    Create a Notion task for an infrastructure/monitoring incident.
    Uses project="Infrastructure", type="monitoring"; priority is inferred.

    Example:
        create_incident_task(
            title="Dashboard health check failed",
            details="GET /api/health returned 503",
            github_link="https://github.com/org/repo/actions/runs/123",
        )
    """
    logger.info("Creating incident task in Notion title=%r", title)
    return create_notion_task(
        title=title,
        project="Infrastructure",
        type="monitoring",
        details=details,
        github_link=github_link,
        status="planned",
        source=source,
    )


def create_bug_task(
    title: str,
    project: str,
    details: str = "",
    github_link: Optional[str] = None,
    source: str = "openclaw",
) -> Optional[dict[str, Any]]:
    """
    Create a Notion task for a bug. Type is "bug"; priority is inferred.

    Example:
        create_bug_task(
            title="Exchange sync timeout under load",
            project="Backend",
            details="ExchangeSyncService times out when order history is large.",
            github_link="https://github.com/org/repo/blob/main/backend/app/services/exchange_sync.py",
        )
    """
    logger.info("Creating bug task in Notion title=%r project=%r", title, project)
    return create_notion_task(
        title=title,
        project=project,
        type="bug",
        details=details,
        github_link=github_link,
        status="planned",
        source=source,
    )


def create_improvement_task(
    title: str,
    project: str,
    details: str = "",
    github_link: Optional[str] = None,
    source: str = "openclaw",
) -> Optional[dict[str, Any]]:
    """
    Create a Notion task for an improvement. Type is "improvement"; priority is inferred.

    Example:
        create_improvement_task(
            title="Add retry for exchange sync",
            project="Backend",
            details="ExchangeSyncService timeouts on peak load; add exponential backoff.",
            github_link="https://github.com/org/repo/blob/main/backend/app/services/exchange_sync.py",
        )
    """
    logger.info("Creating improvement task in Notion title=%r project=%r", title, project)
    return create_notion_task(
        title=title,
        project=project,
        type="improvement",
        details=details,
        github_link=github_link,
        status="planned",
        source=source,
    )


# ---------------------------------------------------------------------------
# Status updates (read/write safe helpers for agents)
# ---------------------------------------------------------------------------


def update_notion_task_status(
    page_id: str,
    status: str,
    *,
    append_comment: str | None = None,
) -> bool:
    """
    Update the "Status" property of an existing Notion task page.

    This function is designed for OpenClaw and other agents to safely update the
    task lifecycle in Notion without breaking production flow.

    Allowed statuses (current lifecycle):
        planned → in-progress → testing → deployed

    Args:
        page_id: Notion page ID to update.
        status: Target status. Must be one of: planned, in-progress, testing, deployed.
        append_comment: Optional comment to append to the page content (best-effort).

    Returns:
        True on successful status update, False otherwise. Never raises.

    Example:
        from app.services.notion_tasks import update_notion_task_status

        ok = update_notion_task_status(
            page_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            status="in-progress",
            append_comment="Picked up by OpenClaw; starting investigation and plan.",
        )
    """
    normalized_page_id = (page_id or "").strip()
    normalized_status = (status or "").strip().lower()

    if not normalized_page_id:
        logger.warning("Notion status update skipped: empty page_id status=%r", normalized_status)
        return False

    if normalized_status not in ALLOWED_TASK_STATUSES:
        logger.warning(
            "Notion status update rejected: invalid status=%r page_id=%s allowed=%s",
            normalized_status,
            normalized_page_id,
            ",".join(ALLOWED_TASK_STATUSES),
        )
        return False

    api_key, _database_id = _get_config()
    if not api_key:
        logger.warning(
            "Notion status update skipped: NOTION_API_KEY not set page_id=%s status=%s",
            normalized_page_id,
            normalized_status,
        )
        return False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    # Keep compatibility with current writer behavior: Status is written as rich_text.
    # For Notion DBs configured with Select for Status, we try a minimal fallback.
    payload_rich_text: dict[str, Any] = {
        "properties": {
            "Status": {"rich_text": _rich_text(normalized_status)},
        }
    }
    payload_select: dict[str, Any] = {
        "properties": {
            "Status": {"select": {"name": normalized_status}},
        }
    }

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.patch(
                f"{NOTION_API_BASE}/pages/{normalized_page_id}",
                json=payload_rich_text,
                headers=headers,
            )

            # Fallback: if Status is a Select in the Notion schema, retry with select payload.
            if response.status_code != 200:
                response2 = client.patch(
                    f"{NOTION_API_BASE}/pages/{normalized_page_id}",
                    json=payload_select,
                    headers=headers,
                )
            else:
                response2 = None

    except httpx.TimeoutException as e:
        logger.warning(
            "Notion status update timed out page_id=%s status=%s err=%s",
            normalized_page_id,
            normalized_status,
            e,
        )
        return False
    except httpx.RequestError as e:
        logger.warning(
            "Notion status update request failed page_id=%s status=%s err=%s",
            normalized_page_id,
            normalized_status,
            e,
        )
        return False
    except Exception as e:
        logger.error(
            "Notion status update failed page_id=%s status=%s err=%s",
            normalized_page_id,
            normalized_status,
            e,
            exc_info=True,
        )
        return False

    final_response = response if response.status_code == 200 else (response2 or response)
    if final_response.status_code != 200:
        try:
            err_body = (final_response.text or "")[:500]
        except Exception:
            err_body = ""
        logger.error(
            "Notion status update API error page_id=%s status=%s http=%d body=%s",
            normalized_page_id,
            normalized_status,
            final_response.status_code,
            err_body,
        )
        return False

    logger.info(
        "Notion status updated successfully page_id=%s status=%s",
        normalized_page_id,
        normalized_status,
    )

    comment = (append_comment or "").strip()
    if comment and not _append_page_comment(normalized_page_id, comment, headers):
        logger.warning(
            "Notion status comment append failed page_id=%s status=%s",
            normalized_page_id,
            normalized_status,
        )

    return True


def update_notion_task_version_metadata(
    page_id: str,
    metadata: dict[str, Any],
    *,
    append_comment: str | None = None,
) -> dict[str, Any]:
    """
    Best-effort update of version metadata properties on a Notion task page.

    Backward compatibility:
    - If a property does not exist in the Notion DB schema, it is skipped.
    - A failure on one property does not block others.
    - Returns a structured result and never raises.
    """
    normalized_page_id = (page_id or "").strip()
    if not normalized_page_id:
        return {"ok": False, "updated_fields": [], "skipped_fields": ["*"], "reason": "empty page_id"}

    if not isinstance(metadata, dict) or not metadata:
        return {"ok": False, "updated_fields": [], "skipped_fields": [], "reason": "empty metadata"}

    api_key, _database_id = _get_config()
    if not api_key:
        logger.warning("Notion version metadata update skipped: NOTION_API_KEY not set page_id=%s", normalized_page_id)
        return {"ok": False, "updated_fields": [], "skipped_fields": list(metadata.keys()), "reason": "missing api key"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    updated_fields: list[str] = []
    skipped_fields: list[str] = []

    def _payload_for(prop_name: str, key: str, value: Any, use_select: bool) -> dict[str, Any]:
        text_value = str(value or "").strip()
        if key == "version_status" and use_select:
            return {"properties": {prop_name: {"select": {"name": text_value}}}}
        return {"properties": {prop_name: {"rich_text": _rich_text(text_value)}}}

    try:
        with httpx.Client(timeout=15.0) as client:
            for key, value in metadata.items():
                if key not in VERSION_PROPERTY_MAP:
                    skipped_fields.append(key)
                    continue
                prop_name = VERSION_PROPERTY_MAP[key]
                text_value = str(value or "").strip()
                if not text_value:
                    skipped_fields.append(key)
                    continue

                payload_primary = _payload_for(prop_name, key, text_value, use_select=False)
                r = client.patch(
                    f"{NOTION_API_BASE}/pages/{normalized_page_id}",
                    json=payload_primary,
                    headers=headers,
                )

                if r.status_code != 200 and key == "version_status":
                    payload_fallback = _payload_for(prop_name, key, text_value, use_select=True)
                    r = client.patch(
                        f"{NOTION_API_BASE}/pages/{normalized_page_id}",
                        json=payload_fallback,
                        headers=headers,
                    )

                if r.status_code == 200:
                    updated_fields.append(key)
                else:
                    skipped_fields.append(key)
                    try:
                        err_body = (r.text or "")[:240]
                    except Exception:
                        err_body = ""
                    logger.info(
                        "Notion version field skipped page_id=%s field=%s http=%d body=%s",
                        normalized_page_id,
                        key,
                        r.status_code,
                        err_body,
                    )
    except Exception as e:
        logger.warning("Notion version metadata update failed page_id=%s err=%s", normalized_page_id, e)
        return {
            "ok": False,
            "updated_fields": updated_fields,
            "skipped_fields": sorted(set(skipped_fields + [k for k in metadata.keys() if k not in updated_fields])),
            "reason": str(e),
        }

    comment = (append_comment or "").strip()
    if comment:
        _append_page_comment(normalized_page_id, comment, headers)

    return {
        "ok": bool(updated_fields),
        "updated_fields": updated_fields,
        "skipped_fields": sorted(set(skipped_fields)),
    }


def update_notion_task_metadata(
    page_id: str,
    metadata: dict[str, Any],
    *,
    append_comment: str | None = None,
) -> dict[str, Any]:
    """
    Best-effort update of extended task metadata properties on a Notion task page.

    Accepts keys from TASK_METADATA_PROPERTY_MAP (risk_level, repo, environment,
    openclaw_report_url, cursor_patch_url, test_status, deploy_approval,
    final_result).  Unknown keys are silently skipped so callers can pass
    partial dicts safely.

    Follows the same pattern as update_notion_task_version_metadata:
    - Each field is written independently; one failure does not block others.
    - Returns a structured result and never raises.
    """
    normalized_page_id = (page_id or "").strip()
    if not normalized_page_id:
        return {"ok": False, "updated_fields": [], "skipped_fields": ["*"], "reason": "empty page_id"}

    if not isinstance(metadata, dict) or not metadata:
        return {"ok": False, "updated_fields": [], "skipped_fields": [], "reason": "empty metadata"}

    api_key, _database_id = _get_config()
    if not api_key:
        logger.warning("Notion task metadata update skipped: NOTION_API_KEY not set page_id=%s", normalized_page_id)
        return {"ok": False, "updated_fields": [], "skipped_fields": list(metadata.keys()), "reason": "missing api key"}

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    updated_fields: list[str] = []
    skipped_fields: list[str] = []
    schema_missing_fields: list[str] = []

    try:
        with httpx.Client(timeout=15.0) as client:
            for key, value in metadata.items():
                if key not in TASK_METADATA_PROPERTY_MAP:
                    skipped_fields.append(key)
                    continue
                prop_name = TASK_METADATA_PROPERTY_MAP[key]
                text_value = str(value or "").strip()
                if not text_value:
                    skipped_fields.append(key)
                    continue

                payload: dict[str, Any] = {
                    "properties": {prop_name: {"rich_text": _rich_text(text_value)}}
                }
                r = client.patch(
                    f"{NOTION_API_BASE}/pages/{normalized_page_id}",
                    json=payload,
                    headers=headers,
                )

                if r.status_code == 200:
                    updated_fields.append(key)
                else:
                    skipped_fields.append(key)
                    try:
                        err_body = (r.text or "")[:240]
                    except Exception:
                        err_body = ""
                    if r.status_code == 400 and "is not a property that exists" in err_body:
                        schema_missing_fields.append(key)
                    logger.info(
                        "Notion metadata field skipped page_id=%s field=%s http=%d body=%s",
                        normalized_page_id, key, r.status_code, err_body,
                    )
    except Exception as e:
        logger.warning("Notion task metadata update failed page_id=%s err=%s", normalized_page_id, e)
        return {
            "ok": False,
            "updated_fields": updated_fields,
            "skipped_fields": sorted(set(skipped_fields + [k for k in metadata if k not in updated_fields])),
            "schema_missing_fields": sorted(set(schema_missing_fields)),
            "reason": str(e),
        }

    comment = (append_comment or "").strip()
    if comment:
        _append_page_comment(normalized_page_id, comment, headers)

    all_schema_missing = (
        bool(skipped_fields)
        and not updated_fields
        and set(skipped_fields) <= set(schema_missing_fields)
    )
    if all_schema_missing:
        logger.info(
            "Notion metadata: all skipped fields are missing from DB schema — "
            "treating as ok page_id=%s schema_missing=%s",
            normalized_page_id, schema_missing_fields,
        )

    return {
        "ok": bool(updated_fields) or all_schema_missing,
        "updated_fields": updated_fields,
        "skipped_fields": sorted(set(skipped_fields)),
        "schema_missing_fields": sorted(set(schema_missing_fields)),
    }


def advance_notion_task_status(
    page_id: str,
    current_status: str,
    *,
    use_extended_lifecycle: bool = False,
) -> bool:
    """
    Advance a Notion task forward by one lifecycle step.

    Legacy mapping (default, use_extended_lifecycle=False):
        planned -> in-progress -> testing -> deployed

    Extended mapping (use_extended_lifecycle=True):
        backlog -> ready-for-investigation -> investigating ->
        investigation-complete -> ready-for-patch -> patching ->
        testing -> awaiting-deploy-approval -> deploying -> done

    Terminal statuses (done, deployed, rejected) return False (no-op).
    Never raises.
    """
    normalized_current = (current_status or "").strip().lower()

    if normalized_current in TERMINAL_STATUSES:
        logger.info("Notion status advance skipped: terminal status=%s page_id=%s", normalized_current, (page_id or "").strip())
        return False

    if use_extended_lifecycle:
        transitions = EXTENDED_LIFECYCLE_TRANSITIONS
    else:
        transitions = LEGACY_LIFECYCLE_TRANSITIONS

    next_status = transitions.get(normalized_current)
    if not next_status:
        logger.warning(
            "Notion status advance rejected: unknown current_status=%r page_id=%s lifecycle=%s",
            normalized_current,
            (page_id or "").strip(),
            "extended" if use_extended_lifecycle else "legacy",
        )
        return False

    ok = update_notion_task_status((page_id or "").strip(), next_status)
    if ok:
        logger.info(
            "Notion status advanced page_id=%s from=%s to=%s",
            (page_id or "").strip(),
            normalized_current,
            next_status,
        )
    else:
        logger.warning(
            "Notion status advance failed page_id=%s from=%s to=%s",
            (page_id or "").strip(),
            normalized_current,
            next_status,
        )
    return ok


# ---------------------------------------------------------------------------
# Example usage (trading bot, monitoring, OpenClaw)
# ---------------------------------------------------------------------------
#
# from app.services.notion_tasks import create_notion_task
#
# create_notion_task(
#     title="Dashboard health check failed",
#     project="Operations",
#     type="incident",
#     priority="high",
#     details="GET /api/health returned 503 at 2026-03-06T12:00:00Z",
#     github_link="https://github.com/org/repo/actions/runs/123",
# )
#
# create_notion_task(
#     title="Add retry for exchange sync",
#     project="Backend",
#     type="improvement",
#     priority="medium",
#     details="ExchangeSyncService timeouts on peak load.",
#     github_link="https://github.com/org/repo/blob/main/backend/app/services/exchange_sync.py",
#     source="openclaw",
# )
