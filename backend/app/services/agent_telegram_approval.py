"""
Telegram approval flow for agent task execution.

Sends approval requests to Telegram with inline buttons (Approve / Deny / View Summary).
Only authorized users may approve or deny. Approval state is persisted in the database
(agent_approval_states); in-memory store is used only as a short-lived cache.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

# Callback data format (stable, short)
PREFIX_APPROVE = "agent_approve:"
PREFIX_DENY = "agent_deny:"
PREFIX_SUMMARY = "agent_summary:"
PREFIX_EXECUTE = "agent_execute:"

# Extended lifecycle callback data prefixes
PREFIX_APPROVE_PATCH = "patch_approve:"
PREFIX_APPROVE_DEPLOY = "deploy_approve:"
PREFIX_REJECT = "task_reject:"
PREFIX_VIEW_REPORT = "view_report:"
PREFIX_SMOKE_CHECK = "smoke_check:"

# In-memory cache: task_id -> { prepared_bundle, status, requested_at, approved_by, decision_at }
# DB is source of truth; memory is optional cache for same-process fast path.
_APPROVAL_STORE: dict[str, dict[str, Any]] = {}
_STORE_LOCK = threading.Lock()

# Lightweight cache for OpenClaw structured sections (task_id → sections dict).
# Populated when investigation-complete or patch-deploy approval messages are sent.
_SECTIONS_CACHE: dict[str, dict[str, Any]] = {}

# Telegram message length limit
TELEGRAM_TEXT_LIMIT = 4096


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_bot_token() -> str:
    return (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()


def _get_default_chat_id() -> str:
    return (os.environ.get("TELEGRAM_CHAT_ID") or "").strip()


def _send_telegram_message(
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
) -> tuple[bool, int | None]:
    """
    Send a text message to Telegram. Returns (success, message_id or None).
    """
    token = _get_bot_token()
    if not token or not chat_id:
        logger.warning("agent_telegram_approval: missing TELEGRAM_BOT_TOKEN or chat_id")
        return False, None
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."
    try:
        from app.utils.http_client import http_post
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup
        r = http_post(url, json=payload, timeout=10, calling_module="agent_telegram_approval")
        if r.status_code != 200:
            logger.warning("agent_telegram_approval: sendMessage failed status=%s body=%s", r.status_code, (r.text or "")[:200])
            return False, None
        data = r.json()
        if not data.get("ok"):
            return False, None
        result = data.get("result") or {}
        return True, result.get("message_id")
    except Exception as e:
        logger.exception("agent_telegram_approval: send failed %s", e)
        return False, None


def _get_db_session():
    """Return a DB session if available; otherwise None. Caller must close/commit/rollback."""
    try:
        from app.database import SessionLocal
        if SessionLocal is None:
            return None
        return SessionLocal()
    except Exception:
        return None


def _serialize_prepared_bundle(prepared_bundle: dict[str, Any]) -> str:
    """
    Serialize bundle to JSON for DB storage. Callables (apply_change_fn, validate_fn, deploy_fn)
    are not serializable; we store only prepared_task, approval, approval_summary, and
    selection_reason so callbacks can be re-selected on load.
    """
    prepared_task = (prepared_bundle or {}).get("prepared_task")
    approval = (prepared_bundle or {}).get("approval") or {}
    approval_summary = (prepared_bundle or {}).get("approval_summary") or ""
    callback_selection = (prepared_bundle or {}).get("callback_selection") or {}
    selection_reason = str(callback_selection.get("selection_reason") or "").strip()
    versioning = _extract_versioning_from_bundle(prepared_bundle)
    payload = {
        "prepared_task": prepared_task,
        "approval": approval,
        "approval_summary": approval_summary,
        "selection_reason": selection_reason,
        "versioning": versioning,
    }
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError) as e:
        logger.warning("agent_telegram_approval: serialize bundle failed %s", e)
        return "{}"


def _deserialize_prepared_bundle(json_str: str | None) -> dict[str, Any] | None:
    """
    Reconstruct a full prepared_bundle from stored JSON. Callbacks are re-selected via
    select_default_callbacks_for_task(prepared_task) since they cannot be serialized.
    """
    if not (json_str or "").strip():
        return None
    try:
        data = json.loads(json_str)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning("agent_telegram_approval: deserialize bundle failed %s", e)
        return None
    prepared_task = data.get("prepared_task")
    if not prepared_task:
        return None
    try:
        from app.services.agent_callbacks import select_default_callbacks_for_task
        callback_selection = select_default_callbacks_for_task(prepared_task)
        logger.info(
            "agent_telegram_approval: callback re-selection result: apply=%s reason=%r task_type=%r",
            "yes" if callback_selection.get("apply_change_fn") else "NO",
            callback_selection.get("selection_reason", ""),
            ((prepared_task.get("task") or {}).get("type") or ""),
        )
    except Exception as e:
        logger.error("agent_telegram_approval: callback re-selection FAILED %s", e, exc_info=True)
        callback_selection = {"apply_change_fn": None, "validate_fn": None, "deploy_fn": None, "selection_reason": data.get("selection_reason", "")}
    return {
        "prepared_task": prepared_task,
        "callback_selection": callback_selection,
        "approval": data.get("approval") or {},
        "approval_summary": (data.get("approval_summary") or "").strip(),
        "versioning": data.get("versioning") or (prepared_task.get("versioning") or {}),
    }


def _extract_versioning_from_bundle(prepared_bundle: dict[str, Any] | None) -> dict[str, Any]:
    bundle = prepared_bundle or {}
    direct = bundle.get("versioning") or {}
    if isinstance(direct, dict) and direct:
        return direct
    prepared_task = bundle.get("prepared_task") or {}
    fallback = prepared_task.get("versioning") or {}
    return fallback if isinstance(fallback, dict) else {}


def send_task_approval_request(
    prepared_bundle: dict[str, Any],
    chat_id: str | None = None,
) -> dict[str, Any]:
    """
    Build a Telegram message from the approval summary and task metadata, send it with
    Approve / Deny / View Summary buttons, and store the bundle for later decision.

    Returns:
        { "sent": bool, "chat_id": str, "task_id": str, "message_id": int | None, "summary": str }
    """
    task = (prepared_bundle or {}).get("prepared_task") or {}
    task_obj = task.get("task") or {}
    approval = (prepared_bundle or {}).get("approval") or {}
    approval_summary = (prepared_bundle or {}).get("approval_summary") or ""
    callback_selection = (prepared_bundle or {}).get("callback_selection") or {}

    task_id = str(task_obj.get("id") or "").strip()
    title = str(task_obj.get("task") or "").strip() or "(no title)"
    priority = str(task_obj.get("priority") or "").strip() or "(none)"
    repo_area = (prepared_bundle or {}).get("prepared_task", {}).get("repo_area") or {}
    area_name = str(repo_area.get("area_name") or "").strip() or "(none)"
    selection_reason = str(callback_selection.get("selection_reason") or "").strip() or "(none)"
    risk_level = str(approval.get("risk_level") or "").strip() or "unknown"
    required = bool(approval.get("required"))
    versioning = _extract_versioning_from_bundle(prepared_bundle)
    proposed_version = str(versioning.get("proposed_version") or task_obj.get("proposed_version") or "").strip()
    change_summary = str(versioning.get("change_summary") or task_obj.get("change_summary") or "").strip()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None, "summary": "missing task_id"}

    target_chat = (chat_id or "").strip() or _get_default_chat_id()
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None, "summary": "no chat_id"}

    # Build message (Telegram-friendly)
    lines = [
        "<b>🔐 Agent task approval</b>",
        "",
        f"<b>Task:</b> {title[:200]}",
        f"<b>Priority:</b> {priority}",
        f"<b>Area:</b> {area_name}",
        f"<b>Callback:</b> {selection_reason[:150]}",
        f"<b>Risk:</b> {risk_level} · Approval required: {required}",
        f"<b>Proposed version:</b> {('v' + proposed_version) if proposed_version else '(none)'}",
        f"<b>Change summary:</b> {(change_summary[:180] if change_summary else '(none)')}",
        "",
        "<pre>" + approval_summary.replace("<", "&lt;")[:2000] + "</pre>",
    ]
    text = "\n".join(lines)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    # Inline keyboard: Approve, Deny, View Summary (callback_data max 64 bytes; task_id is UUID 36 chars)
    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve", "callback_data": f"{PREFIX_APPROVE}{task_id}"},
                {"text": "❌ Deny", "callback_data": f"{PREFIX_DENY}{task_id}"},
            ],
            [{"text": "📄 View Summary", "callback_data": f"{PREFIX_SUMMARY}{task_id}"}],
        ]
    }

    requested_at_iso = _utc_now_iso()
    bundle_json = _serialize_prepared_bundle(prepared_bundle)

    # Persist to DB first (source of truth)
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
            if row:
                row.status = "pending"
                row.requested_at = datetime.now(timezone.utc)
                row.approval_summary = approval_summary[:5000] if approval_summary else None
                row.prepared_bundle_json = bundle_json
                row.approved_by = None
                row.decision_at = None
            else:
                row = AgentApprovalState(
                    task_id=task_id,
                    status="pending",
                    approval_summary=approval_summary[:5000] if approval_summary else None,
                    prepared_bundle_json=bundle_json,
                )
                db.add(row)
            db.commit()
        except Exception as e:
            logger.warning("agent_telegram_approval: failed to persist approval request %s", e)
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
        finally:
            try:
                db.close()
            except Exception:
                pass

    # Cache in memory for same-process fast path
    with _STORE_LOCK:
        _APPROVAL_STORE[task_id] = {
            "prepared_bundle": prepared_bundle,
            "status": "pending",
            "requested_at": requested_at_iso,
            "approved_by": "",
            "decision_at": "",
        }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup)
    if not sent:
        with _STORE_LOCK:
            _APPROVAL_STORE.pop(task_id, None)
        return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None, "summary": "send failed"}

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "approval_requested",
            task_id=task_id,
            task_title=title,
            details={"chat_id": target_chat, "sent": True, "message_id": message_id},
        )
    except Exception:
        pass
    return {
        "sent": True,
        "chat_id": target_chat,
        "task_id": task_id,
        "message_id": message_id,
        "summary": approval_summary[:500],
    }


def get_task_approval_decision(task_id: str) -> dict[str, Any] | None:
    """
    Return current decision for a task, or None if not found.
    DB is source of truth; falls back to in-memory cache if no DB row.

    Returns:
        { "status": "pending" | "approved" | "denied", "approved_by": str, "decision_at": str }
    """
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
            if row:
                decision_at = row.decision_at
                if decision_at is not None and hasattr(decision_at, "isoformat"):
                    decision_at = decision_at.isoformat()
                elif decision_at is not None:
                    decision_at = str(decision_at)
                return {
                    "status": (row.status or "pending"),
                    "approved_by": (row.approved_by or ""),
                    "decision_at": decision_at or "",
                }
        except Exception as e:
            logger.warning("agent_telegram_approval: get_task_approval_decision db read failed %s", e)
        finally:
            try:
                db.close()
            except Exception:
                pass
    with _STORE_LOCK:
        entry = _APPROVAL_STORE.get(task_id)
    if not entry:
        return None
    return {
        "status": entry.get("status", "pending"),
        "approved_by": entry.get("approved_by", ""),
        "decision_at": entry.get("decision_at", ""),
    }


def record_approval(task_id: str, user_id: str, username: str = "") -> bool:
    """Record that an authorized user approved the task. Returns True if state was pending and is now approved."""
    task_id = (task_id or "").strip()
    who = username or user_id or "unknown"
    now = datetime.now(timezone.utc)
    updated = False
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
            if row and (row.status or "").lower() == "pending":
                row.status = "approved"
                row.approved_by = who
                row.decision_at = now
                db.commit()
                updated = True
                with _STORE_LOCK:
                    if task_id in _APPROVAL_STORE:
                        _APPROVAL_STORE[task_id]["status"] = "approved"
                        _APPROVAL_STORE[task_id]["approved_by"] = who
                        _APPROVAL_STORE[task_id]["decision_at"] = now.isoformat()
        except Exception as e:
            logger.warning("agent_telegram_approval: record_approval db update failed %s", e)
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
        finally:
            try:
                db.close()
            except Exception:
                pass
    if not updated:
        with _STORE_LOCK:
            entry = _APPROVAL_STORE.get(task_id)
            if not entry or entry.get("status") != "pending":
                return False
            entry["status"] = "approved"
            entry["approved_by"] = who
            entry["decision_at"] = _utc_now_iso()
            updated = True
    if updated:
        try:
            prepared_bundle = load_prepared_bundle_for_execution(task_id)
            versioning = _extract_versioning_from_bundle(prepared_bundle)
            proposed = str(versioning.get("proposed_version") or "").strip()
            if proposed:
                from app.services.notion_tasks import update_notion_task_version_metadata
                update_notion_task_version_metadata(
                    page_id=task_id,
                    metadata={
                        "proposed_version": proposed,
                        "approved_version": proposed,
                        "version_status": "approved",
                        "change_summary": str(versioning.get("change_summary") or "").strip(),
                    },
                    append_comment=f"Version approved by {who}: v{proposed}",
                )
        except Exception as e:
            logger.debug("agent_telegram_approval: version approved metadata update failed %s", e)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("approval_granted", task_id=task_id, details={"approved_by": who})
    except Exception:
        pass
    return updated


def record_denial(task_id: str, user_id: str, username: str = "") -> bool:
    """Record that an authorized user denied the task. Returns True if state was pending and is now denied."""
    task_id = (task_id or "").strip()
    who = username or user_id or "unknown"
    now = datetime.now(timezone.utc)
    updated = False
    versioning_for_comment: dict[str, Any] = {}
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
            if row and (row.status or "").lower() == "pending":
                if (row.prepared_bundle_json or "").strip():
                    try:
                        data = json.loads(row.prepared_bundle_json)
                        versioning_for_comment = data.get("versioning") or ((data.get("prepared_task") or {}).get("versioning") or {})
                    except Exception:
                        versioning_for_comment = {}
                row.status = "denied"
                row.approved_by = who
                row.decision_at = now
                db.commit()
                updated = True
                with _STORE_LOCK:
                    if task_id in _APPROVAL_STORE:
                        _APPROVAL_STORE[task_id]["status"] = "denied"
                        _APPROVAL_STORE[task_id]["approved_by"] = who
                        _APPROVAL_STORE[task_id]["decision_at"] = now.isoformat()
        except Exception as e:
            logger.warning("agent_telegram_approval: record_denial db update failed %s", e)
            if db:
                try:
                    db.rollback()
                except Exception:
                    pass
        finally:
            try:
                db.close()
            except Exception:
                pass
    if not updated:
        with _STORE_LOCK:
            entry = _APPROVAL_STORE.get(task_id)
            if not entry or entry.get("status") != "pending":
                return False
            versioning_for_comment = _extract_versioning_from_bundle(entry.get("prepared_bundle") or {})
            entry["status"] = "denied"
            entry["approved_by"] = who
            entry["decision_at"] = _utc_now_iso()
            updated = True
    if updated:
        try:
            from app.services.notion_tasks import update_notion_task_version_metadata
            update_notion_task_version_metadata(
                page_id=task_id,
                metadata={
                    "version_status": "rejected",
                    "change_summary": str(versioning_for_comment.get("change_summary") or "").strip(),
                },
                append_comment=f"Version proposal rejected by {who}.",
            )
        except Exception as e:
            logger.debug("agent_telegram_approval: version rejected metadata update failed %s", e)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("approval_denied", task_id=task_id, details={"denied_by": who})
    except Exception:
        pass
    return updated


def get_pending_approvals() -> list[dict[str, Any]]:
    """Return pending approvals for display in Telegram or other read-only surfaces. DB is source of truth."""
    results: list[dict[str, Any]] = []
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            rows = db.query(AgentApprovalState).filter_by(status="pending").order_by(AgentApprovalState.requested_at.desc()).all()
            for row in rows:
                task_title = "(no title)"
                if row.prepared_bundle_json:
                    try:
                        data = json.loads(row.prepared_bundle_json)
                        pt = data.get("prepared_task") or {}
                        task_obj = pt.get("task") or {}
                        task_title = str(task_obj.get("task") or "").strip() or "(no title)"
                    except Exception:
                        pass
                requested_at = ""
                if row.requested_at is not None:
                    requested_at = row.requested_at.isoformat() if hasattr(row.requested_at, "isoformat") else str(row.requested_at)
                results.append({"task_id": row.task_id, "task_title": task_title, "requested_at": requested_at})
            if results:
                return results
        except Exception as e:
            logger.warning("agent_telegram_approval: get_pending_approvals db read failed %s", e)
        finally:
            try:
                db.close()
            except Exception:
                pass
    with _STORE_LOCK:
        for task_id, entry in _APPROVAL_STORE.items():
            if entry.get("status") != "pending":
                continue
            bundle = entry.get("prepared_bundle") or {}
            task = (bundle.get("prepared_task") or {}).get("task") or {}
            results.append(
                {
                    "task_id": task_id,
                    "task_title": str(task.get("task") or "").strip() or "(no title)",
                    "requested_at": str(entry.get("requested_at") or "").strip(),
                }
            )
    return results


def get_approval_summary_text(task_id: str) -> str:
    """Return the approval_summary text for the task, or a short fallback if not found. DB first."""
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
            if row and (row.approval_summary or "").strip():
                return (row.approval_summary or "").strip()
        except Exception as e:
            logger.warning("agent_telegram_approval: get_approval_summary_text db read failed %s", e)
        finally:
            try:
                db.close()
            except Exception:
                pass
    with _STORE_LOCK:
        entry = _APPROVAL_STORE.get(task_id)
    if not entry:
        return f"No approval request found for task {task_id}."
    bundle = entry.get("prepared_bundle") or {}
    return (bundle.get("approval_summary") or "").strip() or "No summary stored."


def get_approval_request_detail(task_id: str) -> dict[str, Any] | None:
    """
    Return a structured detail object for an approval request. DB is source of truth.
    Includes task_id, status, requested_at, approved_by, decision_at, approval_summary,
    prepared_task metadata (task title, project, type, priority, source), selection_reason,
    and inferred repo area when available. Returns None if the row does not exist.
    """
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is None:
        with _STORE_LOCK:
            entry = _APPROVAL_STORE.get(task_id)
            if not entry:
                return None
            bundle = entry.get("prepared_bundle") or {}
            pt = bundle.get("prepared_task") or {}
            task_obj = pt.get("task") or {}
            repo_area = pt.get("repo_area") or {}
            cs = bundle.get("callback_selection") or {}
            requested_at = entry.get("requested_at") or ""
            decision_at = entry.get("decision_at") or ""
            return {
                "task_id": task_id,
                "status": entry.get("status", "pending"),
                "requested_at": requested_at,
                "approved_by": entry.get("approved_by", ""),
                "decision_at": decision_at,
                "approval_summary": (bundle.get("approval_summary") or "").strip(),
                "task_title": str(task_obj.get("task") or "").strip() or "(no title)",
                "project": str(task_obj.get("project") or "").strip(),
                "type": str(task_obj.get("type") or "").strip(),
                "priority": str(task_obj.get("priority") or "").strip(),
                "source": str(task_obj.get("source") or "").strip(),
                "selection_reason": str(cs.get("selection_reason") or "").strip(),
                "repo_area": repo_area,
                "execution_status": "not_started",
                "execution_started_at": "",
                "executed_at": "",
                "execution_summary": "",
                "current_version": str(task_obj.get("current_version") or "").strip(),
                "proposed_version": str(task_obj.get("proposed_version") or "").strip(),
                "approved_version": str(task_obj.get("approved_version") or "").strip(),
                "released_version": str(task_obj.get("released_version") or "").strip(),
                "version_status": str(task_obj.get("version_status") or "").strip(),
                "change_summary": str(task_obj.get("change_summary") or "").strip(),
            }
    try:
        from app.models.agent_approval_state import AgentApprovalState
        row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
        if not row:
            return None
        requested_at = ""
        if row.requested_at is not None:
            requested_at = row.requested_at.isoformat() if hasattr(row.requested_at, "isoformat") else str(row.requested_at)
        decision_at = ""
        if row.decision_at is not None:
            decision_at = row.decision_at.isoformat() if hasattr(row.decision_at, "isoformat") else str(row.decision_at)
        execution_started_at = ""
        if row.execution_started_at is not None:
            execution_started_at = row.execution_started_at.isoformat() if hasattr(row.execution_started_at, "isoformat") else str(row.execution_started_at)
        executed_at = ""
        if row.executed_at is not None:
            executed_at = row.executed_at.isoformat() if hasattr(row.executed_at, "isoformat") else str(row.executed_at)
        out: dict[str, Any] = {
            "task_id": row.task_id,
            "status": (row.status or "pending"),
            "requested_at": requested_at,
            "approved_by": (row.approved_by or ""),
            "decision_at": decision_at,
            "approval_summary": (row.approval_summary or "").strip(),
            "task_title": "(no title)",
            "project": "",
            "type": "",
            "priority": "",
            "source": "",
            "selection_reason": "",
            "repo_area": {},
            "execution_status": (row.execution_status or "not_started"),
            "execution_started_at": execution_started_at,
            "executed_at": executed_at,
            "execution_summary": (row.execution_summary or "").strip(),
            "current_version": "",
            "proposed_version": "",
            "approved_version": "",
            "released_version": "",
            "version_status": "",
            "change_summary": "",
        }
        if (row.prepared_bundle_json or "").strip():
            try:
                data = json.loads(row.prepared_bundle_json)
                pt = data.get("prepared_task") or {}
                task_obj = pt.get("task") or {}
                versioning = data.get("versioning") or pt.get("versioning") or {}
                out["task_title"] = str(task_obj.get("task") or "").strip() or "(no title)"
                out["project"] = str(task_obj.get("project") or "").strip()
                out["type"] = str(task_obj.get("type") or "").strip()
                out["priority"] = str(task_obj.get("priority") or "").strip()
                out["source"] = str(task_obj.get("source") or "").strip()
                out["selection_reason"] = str(data.get("selection_reason") or "").strip()
                out["repo_area"] = pt.get("repo_area") or {}
                out["current_version"] = str(versioning.get("current_version") or task_obj.get("current_version") or "").strip()
                out["proposed_version"] = str(versioning.get("proposed_version") or task_obj.get("proposed_version") or "").strip()
                out["approved_version"] = str(versioning.get("approved_version") or task_obj.get("approved_version") or "").strip()
                out["released_version"] = str(versioning.get("released_version") or task_obj.get("released_version") or "").strip()
                out["version_status"] = str(versioning.get("version_status") or task_obj.get("version_status") or "").strip()
                out["change_summary"] = str(versioning.get("change_summary") or task_obj.get("change_summary") or "").strip()
            except Exception:
                pass
        return out
    except Exception as e:
        logger.warning("agent_telegram_approval: get_approval_request_detail db read failed %s", e)
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


# Allowed execution_status values for durable execution state
EXECUTION_STATUS_NOT_STARTED = "not_started"
EXECUTION_STATUS_RUNNING = "running"
EXECUTION_STATUS_COMPLETED = "completed"
EXECUTION_STATUS_FAILED = "failed"


def get_task_execution_state(task_id: str) -> dict[str, Any] | None:
    """Return execution state for a task from DB, or None if no record."""
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is None:
        return None
    try:
        from app.models.agent_approval_state import AgentApprovalState
        row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
        if not row:
            return None
        started_at = row.execution_started_at
        executed_at = row.executed_at
        if started_at is not None and hasattr(started_at, "isoformat"):
            started_at = started_at.isoformat()
        elif started_at is not None:
            started_at = str(started_at)
        if executed_at is not None and hasattr(executed_at, "isoformat"):
            executed_at = executed_at.isoformat()
        elif executed_at is not None:
            executed_at = str(executed_at)
        return {
            "execution_status": (row.execution_status or EXECUTION_STATUS_NOT_STARTED),
            "execution_started_at": started_at,
            "executed_at": executed_at,
            "execution_summary": (row.execution_summary or "").strip(),
        }
    except Exception as e:
        logger.warning("agent_telegram_approval: get_task_execution_state failed %s", e)
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def start_task_execution(task_id: str) -> dict[str, Any]:
    """
    Mark task execution as started. Succeeds only when approval is approved and
    execution_status is not already running or completed. On success sets
    execution_status=running, execution_started_at=now.
    """
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is None:
        return {
            "started": False,
            "reason": "database unavailable",
            "execution_status": "missing",
        }
    try:
        from app.models.agent_approval_state import AgentApprovalState
        row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
        if not row:
            return {"started": False, "reason": "no approval record", "execution_status": "missing"}
        if (row.status or "").lower() != "approved":
            return {
                "started": False,
                "reason": f"approval status is {row.status}, not approved",
                "execution_status": (row.execution_status or EXECUTION_STATUS_NOT_STARTED),
            }
        current = (row.execution_status or EXECUTION_STATUS_NOT_STARTED).lower()
        if current == EXECUTION_STATUS_RUNNING:
            return {"started": False, "reason": "execution already running", "execution_status": current}
        if current == EXECUTION_STATUS_COMPLETED:
            return {"started": False, "reason": "execution already completed", "execution_status": current}
        row.execution_status = EXECUTION_STATUS_RUNNING
        row.execution_started_at = datetime.now(timezone.utc)
        db.commit()
        return {"started": True, "reason": "started", "execution_status": EXECUTION_STATUS_RUNNING}
    except Exception as e:
        logger.warning("agent_telegram_approval: start_task_execution failed %s", e)
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return {"started": False, "reason": str(e), "execution_status": "missing"}
    finally:
        try:
            db.close()
        except Exception:
            pass


def complete_task_execution(task_id: str, summary: str = "") -> bool:
    """Set execution_status=completed, executed_at=now, execution_summary=summary."""
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is None:
        return False
    try:
        from app.models.agent_approval_state import AgentApprovalState
        row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
        if not row:
            return False
        row.execution_status = EXECUTION_STATUS_COMPLETED
        row.executed_at = datetime.now(timezone.utc)
        row.execution_summary = (summary or "").strip()[:5000] if summary else None
        db.commit()
        return True
    except Exception as e:
        logger.warning("agent_telegram_approval: complete_task_execution failed %s", e)
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass


MAX_EXECUTION_RETRIES = 3


def fail_task_execution(task_id: str, summary: str = "") -> bool:
    """Set execution_status=failed, increment retry_count, execution_summary=summary."""
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is None:
        return False
    try:
        from app.models.agent_approval_state import AgentApprovalState
        row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
        if not row:
            return False
        row.execution_status = EXECUTION_STATUS_FAILED
        row.execution_summary = (summary or "").strip()[:5000] if summary else None
        current_count = getattr(row, "retry_count", 0) or 0
        row.retry_count = current_count + 1
        if row.retry_count >= MAX_EXECUTION_RETRIES:
            logger.warning(
                "fail_task_execution: retry_count=%d reached MAX_EXECUTION_RETRIES=%d for task_id=%s — "
                "marking completed to stop retries",
                row.retry_count, MAX_EXECUTION_RETRIES, task_id,
            )
            row.execution_status = EXECUTION_STATUS_COMPLETED
            row.execution_summary = (
                f"Exhausted {MAX_EXECUTION_RETRIES} retries. Last failure: "
                + ((summary or "").strip()[:4000])
            )
        db.commit()
        return True
    except Exception as e:
        logger.warning("agent_telegram_approval: fail_task_execution failed %s", e)
        if db:
            try:
                db.rollback()
            except Exception:
                pass
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass


def can_execute_approved_task(task_id: str) -> dict[str, Any]:
    """
    Return whether an already-approved task can be executed from Telegram.
    can_execute is True only if: approval status is approved, bundle can be reconstructed,
    and execution_status is not_started or failed (retry allowed after failure).
    """
    task_id = (task_id or "").strip()
    decision = get_task_approval_decision(task_id)
    if not decision:
        return {
            "can_execute": False,
            "reason": "no approval record found",
            "status": "missing",
            "has_bundle": False,
            "execution_status": "missing",
        }
    status = (decision.get("status") or "").lower()
    if status != "approved":
        return {
            "can_execute": False,
            "reason": f"approval status is {status}, not approved",
            "status": status,
            "has_bundle": False,
            "execution_status": "missing",
        }
    exec_state = get_task_execution_state(task_id)
    execution_status = (exec_state.get("execution_status") or EXECUTION_STATUS_NOT_STARTED).lower() if exec_state else EXECUTION_STATUS_NOT_STARTED
    if execution_status == EXECUTION_STATUS_RUNNING:
        return {
            "can_execute": False,
            "reason": "execution already running",
            "status": status,
            "has_bundle": True,
            "execution_status": execution_status,
        }
    if execution_status == EXECUTION_STATUS_COMPLETED:
        return {
            "can_execute": False,
            "reason": "execution already completed",
            "status": status,
            "has_bundle": True,
            "execution_status": execution_status,
        }
    bundle = load_prepared_bundle_for_execution(task_id)
    if not bundle:
        return {
            "can_execute": False,
            "reason": "could not load or reconstruct prepared bundle",
            "status": status,
            "has_bundle": False,
            "execution_status": execution_status,
        }
    return {
        "can_execute": True,
        "reason": "approved; retry allowed after failure" if execution_status == EXECUTION_STATUS_FAILED else "approved and bundle ready",
        "status": status,
        "has_bundle": True,
        "execution_status": execution_status,
    }


def load_prepared_bundle_for_execution(task_id: str) -> dict[str, Any] | None:
    """
    Reconstruct a prepared_bundle for execution from DB (or memory cache).
    Callbacks are re-selected from stored task metadata since they are not serializable.
    Returns None if not found, not approved, or reconstruction fails.
    """
    task_id = (task_id or "").strip()
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            row = db.query(AgentApprovalState).filter_by(task_id=task_id).first()
            if row and (row.status or "").lower() == "approved" and (row.prepared_bundle_json or "").strip():
                bundle = _deserialize_prepared_bundle(row.prepared_bundle_json)
                if bundle:
                    return bundle
            elif row and (row.status or "").lower() != "approved":
                return None
        except Exception as e:
            logger.warning("agent_telegram_approval: load_prepared_bundle_for_execution db read failed %s", e)
        finally:
            try:
                db.close()
            except Exception:
                pass
    with _STORE_LOCK:
        entry = _APPROVAL_STORE.get(task_id)
        if entry and (entry.get("status") or "").lower() == "approved":
            return entry.get("prepared_bundle")
    return None


def execute_prepared_task_from_telegram_decision(task_id: str) -> dict[str, Any]:
    """
    Start execution guard, run execute_prepared_task_if_approved, then update execution state.
    Does not run if start_task_execution fails (e.g. already running/completed).
    """
    task_id = (task_id or "").strip()
    execution_state_before = get_task_execution_state(task_id)

    decision = get_task_approval_decision(task_id)
    if not decision:
        return {
            "executed": False,
            "task_id": task_id,
            "reason": "no approval record found",
            "execution_result": None,
            "execution_state_before": execution_state_before,
            "execution_started": False,
            "execution_state_after": execution_state_before,
        }
    status = (decision.get("status") or "").lower()
    if status != "approved":
        return {
            "executed": False,
            "task_id": task_id,
            "reason": f"decision is {status}, not approved",
            "execution_result": None,
            "execution_state_before": execution_state_before,
            "execution_started": False,
            "execution_state_after": execution_state_before,
        }
    bundle = load_prepared_bundle_for_execution(task_id)
    if not bundle:
        return {
            "executed": False,
            "task_id": task_id,
            "reason": "could not load or reconstruct prepared bundle",
            "execution_result": None,
            "execution_state_before": execution_state_before,
            "execution_started": False,
            "execution_state_after": execution_state_before,
        }

    start_result = start_task_execution(task_id)
    if not start_result.get("started"):
        return {
            "executed": False,
            "task_id": task_id,
            "reason": start_result.get("reason", "start guard failed"),
            "execution_result": None,
            "execution_state_before": execution_state_before,
            "execution_started": False,
            "execution_state_after": get_task_execution_state(task_id),
        }

    from app.services.agent_task_executor import execute_prepared_task_if_approved
    result = execute_prepared_task_if_approved(bundle, approved=True)
    exec_result = result.get("execution_result")
    success = exec_result.get("success") if isinstance(exec_result, dict) else False
    summary = ""
    if isinstance(exec_result, dict):
        parts = []
        if exec_result.get("final_status"):
            parts.append(f"final_status={exec_result.get('final_status')}")
        if exec_result.get("apply", {}).get("summary"):
            parts.append(exec_result.get("apply", {}).get("summary", "")[:500])
        summary = "; ".join(parts) if parts else str(exec_result.get("final_status") or "")

    if success:
        complete_task_execution(task_id, summary=summary)
    else:
        fail_task_execution(task_id, summary=summary or (result.get("reason") or "execution failed")[:500])

    execution_state_after = get_task_execution_state(task_id)
    return {
        "executed": True,
        "task_id": task_id,
        "reason": result.get("reason", "approved; execution ran"),
        "execution_result": exec_result,
        "execution_state_before": execution_state_before,
        "execution_started": True,
        "execution_state_after": execution_state_after,
    }


def get_approved_retryable_task_ids(max_results: int = 5) -> list[str]:
    """
    Return task_ids that are approved but whose execution failed or never started,
    and whose retry_count has not exceeded MAX_EXECUTION_RETRIES.
    """
    db = _get_db_session()
    if db is None:
        return []
    try:
        from sqlalchemy import or_
        from app.models.agent_approval_state import AgentApprovalState
        retry_col = getattr(AgentApprovalState, "retry_count", None)
        base_filter = [
            AgentApprovalState.status == "approved",
            or_(
                AgentApprovalState.execution_status.in_([
                    EXECUTION_STATUS_FAILED,
                    EXECUTION_STATUS_NOT_STARTED,
                ]),
                AgentApprovalState.execution_status.is_(None),
            ),
        ]
        if retry_col is not None:
            base_filter.append(
                or_(retry_col < MAX_EXECUTION_RETRIES, retry_col.is_(None))
            )
        rows = (
            db.query(AgentApprovalState)
            .filter(*base_filter)
            .limit(max_results)
            .all()
        )
        return [r.task_id for r in rows if r.task_id]
    except Exception as e:
        logger.warning("get_approved_retryable_task_ids failed: %s", e)
        return []
    finally:
        try:
            db.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Extended lifecycle: investigation-complete / patch-deploy approval messages
# ---------------------------------------------------------------------------


def format_openclaw_summary_for_telegram(sections: dict[str, Any]) -> str:
    """Build a short HTML-formatted Telegram summary from OpenClaw structured sections.

    Extracts Task Summary, Risk Level, Affected Files, and Recommended Fix.
    Gracefully handles missing sections (returns what's available).
    """
    parts: list[str] = []

    task_summary = sections.get("Task Summary")
    if task_summary and str(task_summary).strip().lower() != "n/a":
        parts.append(f"<b>Summary:</b> {str(task_summary).strip()[:300]}")

    risk = sections.get("Risk Level")
    if risk and str(risk).strip().lower() != "n/a":
        parts.append(f"<b>Risk:</b> {str(risk).strip().splitlines()[0][:100]}")

    files = sections.get("Affected Files")
    if files and str(files).strip().lower() != "n/a":
        file_lines = [l.strip() for l in str(files).strip().splitlines() if l.strip()][:5]
        parts.append("<b>Files:</b>\n" + "\n".join(file_lines))

    fix = sections.get("Recommended Fix")
    if fix and str(fix).strip().lower() != "n/a":
        parts.append(f"<b>Fix:</b> {str(fix).strip()[:400]}")

    if not parts:
        return "<i>(no structured report available)</i>"
    return "\n\n".join(parts)


def send_investigation_complete_approval(
    task_id: str,
    title: str,
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """Send a Telegram message after OpenClaw investigation completes.

    Buttons: [Approve Patch] [Reject] [View Report]

    Returns ``{"sent": bool, "chat_id": str, "task_id": str, "message_id": int | None}``.
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    sections = sections or {}
    with _STORE_LOCK:
        _SECTIONS_CACHE[task_id] = sections

    summary_html = format_openclaw_summary_for_telegram(sections)
    risk_line = ""
    risk = sections.get("Risk Level")
    if risk and str(risk).strip().lower() != "n/a":
        risk_line = f"<b>Risk Level:</b> {str(risk).strip().splitlines()[0][:80]}\n"

    lines = [
        "<b>🔍 Investigation complete</b>",
        "",
        f"<b>Task:</b> {title}",
        risk_line.rstrip(),
        "",
        summary_html,
    ]
    text = "\n".join(l for l in lines if l is not None)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "✅ Approve Patch", "callback_data": f"{PREFIX_APPROVE_PATCH}{task_id}"},
                {"text": "❌ Reject", "callback_data": f"{PREFIX_REJECT}{task_id}"},
            ],
            [{"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"}],
        ]
    }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup)
    logger.info(
        "send_investigation_complete_approval task_id=%s sent=%s message_id=%s",
        task_id, sent, message_id,
    )

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "investigation_approval_sent",
            task_id=task_id,
            task_title=title,
            details={"chat_id": target_chat, "sent": sent, "message_id": message_id},
        )
    except Exception:
        pass

    return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id}


def send_patch_deploy_approval(
    task_id: str,
    title: str,
    test_summary: str = "",
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """Send a Telegram message after patch + tests complete.

    Buttons: [Approve Deploy] [Reject] [View Report]

    Returns ``{"sent": bool, "chat_id": str, "task_id": str, "message_id": int | None}``.
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    if sections:
        with _STORE_LOCK:
            _SECTIONS_CACHE[task_id] = sections

    test_block = (test_summary or "").strip()[:500] or "(no test output)"

    lines = [
        "<b>🚀 Patch ready for deploy</b>",
        "",
        f"<b>Task:</b> {title}",
        "",
        f"<b>Test results:</b>\n<pre>{test_block}</pre>",
    ]
    text = "\n".join(lines)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "\U0001f680 Approve Deploy", "callback_data": f"{PREFIX_APPROVE_DEPLOY}{task_id}"},
                {"text": "\u274c Reject", "callback_data": f"{PREFIX_REJECT}{task_id}"},
            ],
            [
                {"text": "\U0001f50d Smoke Check", "callback_data": f"{PREFIX_SMOKE_CHECK}{task_id}"},
                {"text": "\U0001f4cb View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"},
            ],
        ]
    }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup)
    logger.info(
        "send_patch_deploy_approval task_id=%s sent=%s message_id=%s",
        task_id, sent, message_id,
    )

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "deploy_approval_sent",
            task_id=task_id,
            task_title=title,
            details={"chat_id": target_chat, "sent": sent, "message_id": message_id},
        )
    except Exception:
        pass

    return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id}


def get_openclaw_report_for_task(task_id: str) -> str:
    """Return the OpenClaw report for a task as Telegram-safe HTML.

    Looks up structured sections from the in-memory cache first.  Falls
    back to loading the ``.sections.json`` sidecar from disk. Returns a
    human-readable fallback if neither source is available.
    """
    task_id = (task_id or "").strip()

    # Try in-memory cache
    with _STORE_LOCK:
        sections = _SECTIONS_CACHE.get(task_id)
    if sections:
        return format_openclaw_summary_for_telegram(sections)

    # Try sidecar files on disk (check all known output directories)
    try:
        import pathlib
        here = pathlib.Path(__file__).resolve()
        for ancestor in here.parents:
            if (ancestor / ".git").is_dir() or (ancestor / "docs").is_dir():
                repo_root = ancestor
                break
        else:
            repo_root = here.parents[min(2, len(here.parents) - 1)]

        search_dirs = [
            repo_root / "docs" / "agents" / "bug-investigations",
            repo_root / "docs" / "agents" / "generated-notes",
            repo_root / "docs" / "runbooks" / "triage",
        ]
        for d in search_dirs:
            for pattern in (f"*-{task_id}.sections.json", f"*{task_id}*.sections.json"):
                for f in d.glob(pattern):
                    data = json.loads(f.read_text(encoding="utf-8"))
                    disk_sections = data.get("sections") or {}
                    if disk_sections:
                        with _STORE_LOCK:
                            _SECTIONS_CACHE[task_id] = disk_sections
                        return format_openclaw_summary_for_telegram(disk_sections)
    except Exception as e:
        logger.debug("get_openclaw_report_for_task: sidecar lookup failed task_id=%s: %s", task_id, e)

    return f"<i>No OpenClaw report cached for task {task_id}.\nCheck the task notes in Notion or docs/agents/ for the full report.</i>"
