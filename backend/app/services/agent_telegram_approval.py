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
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

from app.services.agent_execution_policy import (
    GOVERNANCE_ACTION_CLASS_KEY,
    GOV_CLASS_PATCH_PREP,
    GOV_CLASS_PROD_MUTATION,
)

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
PREFIX_REINVESTIGATE = "reinvestigate:"
PREFIX_RUN_CURSOR_BRIDGE = "run_cursor_bridge:"

# In-memory cache: task_id -> { prepared_bundle, status, requested_at, approved_by, decision_at }
# DB is source of truth; memory is optional cache for same-process fast path.
_APPROVAL_STORE: dict[str, dict[str, Any]] = {}
_STORE_LOCK = threading.Lock()

# Lightweight cache for OpenClaw structured sections (task_id → sections dict).
# Populated when investigation-complete or patch-deploy approval messages are sent.
_SECTIONS_CACHE: dict[str, dict[str, Any]] = {}

# Deduplication: task_id -> timestamp of last deploy approval sent. Prevents re-sending
# the same approval request when advance_ready_for_patch_task runs every scheduler cycle.
_DEPLOY_APPROVAL_SENT: dict[str, float] = {}
_DEPLOY_APPROVAL_DEDUP_HOURS = 24

# Release-candidate approval: DB-backed idempotency per task+version. Survives restarts.
_RELEASE_CANDIDATE_DEDUP_KEY_PREFIX = "agent_release_candidate_approval:"
_RELEASE_CANDIDATE_DEDUP_HOURS = 24 * 7  # 7 days — one approval per task/version
# In-memory fallback when DB write fails after successful send; prevents duplicate within same process.
_SENT_BUT_DEDUP_WRITE_FAILED: set[tuple[str, str]] = set()
_SENT_BUT_DEDUP_WRITE_FAILED_LOCK = threading.Lock()

# Required sections for deploy approval. New artifacts must have these in .sections.json.
# Legacy/backfilled artifacts may use markdown fallback when incomplete.
_REQUIRED_DEPLOY_SECTIONS = ("Task Summary", "Root Cause", "Recommended Fix", "Affected Files")

# Investigation info dedup: DB-backed (TradingSettings). Key: agent_info_dedup:investigation_complete:<task_id>
# Replaces volatile JSONL/memory; survives restarts and is shared across workers.
_AGENT_INFO_DEDUP_KEY_PREFIX = "agent_info_dedup:investigation_complete:"
_INVESTIGATION_INFO_DEDUP_HOURS = 24

# Telegram message length limit
TELEGRAM_TEXT_LIMIT = 4096

# Message type prefixes for clarity (INFO = informational, APPROVAL REQUIRED = human gate, BLOCKER = real blocker)
MSG_PREFIX_INFO = "ℹ️ INFO"
MSG_PREFIX_ACTION = "⚡ ACTION NEEDED"
MSG_PREFIX_APPROVAL = "🔐 APPROVAL REQUIRED"
MSG_PREFIX_BLOCKER = "🚫 BLOCKER"


def _get_notification_mode() -> str:
    """Read TELEGRAM_NOTIFICATION_MODE env. minimal (default) = fewer messages; verbose = more status updates."""
    raw = (os.environ.get("TELEGRAM_NOTIFICATION_MODE") or "").strip().lower()
    if raw in ("verbose", "1", "true", "yes"):
        return "verbose"
    return "minimal"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _get_default_chat_id() -> str:
    """Claw chat ID for task-system messages (TELEGRAM_CLAW_CHAT_ID or fallback TELEGRAM_CHAT_ID)."""
    from app.services.claw_telegram import _get_claw_chat_id
    return _get_claw_chat_id()


def _send_telegram_message(
    chat_id: str,
    text: str,
    reply_markup: dict[str, Any] | None = None,
    *,
    message_type: str = "TASK",
) -> tuple[bool, int | None]:
    """
    Send a text message to Claw bot (task-system channel). Returns (success, message_id or None).
    """
    from app.services.claw_telegram import send_claw_message
    sent, msg_id = send_claw_message(
        text,
        message_type=message_type,
        source_module="agent_telegram_approval",
        reply_markup=reply_markup,
    )
    return sent, msg_id


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
    gov_raw = str(callback_selection.get(GOVERNANCE_ACTION_CLASS_KEY) or "").strip().lower()
    payload = {
        "prepared_task": prepared_task,
        "approval": approval,
        "approval_summary": approval_summary,
        "selection_reason": selection_reason,
        "versioning": versioning,
    }
    if gov_raw in (GOV_CLASS_PATCH_PREP, GOV_CLASS_PROD_MUTATION):
        payload["governance_action_class"] = gov_raw
    try:
        from app.core.environment import getRuntimeEnv
        from app.services.agent_bundle_identity import (
            build_bundle_identity_dict,
            compute_bundle_fingerprint,
            log_bundle_fingerprint_created,
        )
        from app.services.agent_execution_policy import governance_agent_enforcement_context_active

        ident = build_bundle_identity_dict(
            prepared_task if isinstance(prepared_task, dict) else {},
            callback_selection if isinstance(callback_selection, dict) else {},
        )
        fp = compute_bundle_fingerprint(ident)
        payload["bundle_identity"] = ident
        payload["bundle_fingerprint"] = fp
        task_obj = ((prepared_task or {}).get("task") or {}) if isinstance(prepared_task, dict) else {}
        tid = str(task_obj.get("id") or "").strip()
        if tid:
            log_bundle_fingerprint_created(
                notion_task_id=tid,
                fingerprint=fp,
                identity=ident,
                manifest_id=None,
                environment=getRuntimeEnv(),
                enforcement_active=governance_agent_enforcement_context_active(),
                log_context="serialize_prepared_bundle",
            )
    except Exception as e:
        logger.debug("bundle fingerprint at serialize skipped: %s", e)
    try:
        return json.dumps(payload, default=str)
    except (TypeError, ValueError) as e:
        logger.warning("agent_telegram_approval: serialize bundle failed %s", e)
        return "{}"


def _deserialize_prepared_bundle(
    json_str: str | None,
    *,
    execution_load: bool = False,
) -> dict[str, Any] | None:
    """
    Reconstruct a full prepared_bundle from stored JSON. Callbacks are re-selected via
    select_default_callbacks_for_task(prepared_task) since they cannot be serialized.

    When ``execution_load`` is True and ``bundle_fingerprint`` is present on the JSON,
    Notion task type refresh is skipped so callback routing matches the approved snapshot
    (reduces re-selection drift). Legacy rows without a fingerprint keep the refresh behavior.
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

    stored_fp = str(data.get("bundle_fingerprint") or "").strip()
    skip_notion_refresh = bool(execution_load and stored_fp)

    # --- Refresh task type from Notion before callback re-selection --------
    # The stored prepared_task may contain a stale or empty ``type`` if it was
    # serialized before a parser fix.  A single Notion page read ensures the
    # callback selector sees the authoritative Type value.
    task_obj = prepared_task.get("task") or {}
    stored_type = (task_obj.get("type") or "").strip()
    task_id = (task_obj.get("id") or "").strip()

    if task_id and not skip_notion_refresh:
        try:
            from app.services.notion_task_reader import get_notion_task_by_id
            fresh_task = get_notion_task_by_id(task_id)
            if fresh_task:
                fresh_type = (fresh_task.get("type") or "").strip()
                if fresh_type and fresh_type != stored_type:
                    task_obj["type"] = fresh_type
                    logger.info(
                        "_deserialize_prepared_bundle: refreshed task type from Notion "
                        "task_id=%s stored_type=%r fresh_type=%r",
                        task_id[:12], stored_type, fresh_type,
                    )
                elif not fresh_type and stored_type:
                    logger.info(
                        "_deserialize_prepared_bundle: Notion type is empty, keeping stored "
                        "task_id=%s stored_type=%r",
                        task_id[:12], stored_type,
                    )
                else:
                    logger.info(
                        "_deserialize_prepared_bundle: task type unchanged "
                        "task_id=%s type=%r",
                        task_id[:12], stored_type or fresh_type,
                    )
        except Exception as e:
            logger.warning(
                "_deserialize_prepared_bundle: Notion type refresh failed "
                "task_id=%s stored_type=%r — proceeding with stored value: %s",
                task_id[:12], stored_type, e,
            )
    elif skip_notion_refresh:
        logger.info(
            "_deserialize_prepared_bundle: skipping Notion type refresh (execution_load + bundle_fingerprint) "
            "task_id=%s",
            task_id[:12] if task_id else "?",
        )

    effective_type = (task_obj.get("type") or "").strip()

    try:
        from app.services.agent_callbacks import select_default_callbacks_for_task
        callback_selection = select_default_callbacks_for_task(prepared_task)
        sg = str(data.get("governance_action_class") or "").strip().lower()
        if sg in (GOV_CLASS_PATCH_PREP, GOV_CLASS_PROD_MUTATION):
            cur = str(callback_selection.get(GOVERNANCE_ACTION_CLASS_KEY) or "").strip().lower()
            if not cur:
                callback_selection = dict(callback_selection)
                callback_selection[GOVERNANCE_ACTION_CLASS_KEY] = sg
        logger.info(
            "_deserialize_prepared_bundle: CALLBACK RE-SELECTION task_id=%s "
            "stored_type=%r effective_type=%r manual_only=%s "
            "selection_reason=%r apply=%s",
            task_id[:12],
            stored_type,
            effective_type,
            bool(callback_selection.get("manual_only")),
            callback_selection.get("selection_reason", ""),
            "yes" if callback_selection.get("apply_change_fn") else "NO",
        )
    except Exception as e:
        logger.error("_deserialize_prepared_bundle: callback re-selection FAILED %s", e, exc_info=True)
        callback_selection = {"apply_change_fn": None, "validate_fn": None, "deploy_fn": None, "selection_reason": data.get("selection_reason", "")}
    out: dict[str, Any] = {
        "prepared_task": prepared_task,
        "callback_selection": callback_selection,
        "approval": data.get("approval") or {},
        "approval_summary": (data.get("approval_summary") or "").strip(),
        "versioning": data.get("versioning") or (prepared_task.get("versioning") or {}),
    }
    if stored_fp:
        out["bundle_fingerprint_approved"] = stored_fp
    frozen_identity = data.get("bundle_identity")
    if isinstance(frozen_identity, dict):
        out["bundle_identity_approved"] = frozen_identity
    return out


def _extract_versioning_from_bundle(prepared_bundle: dict[str, Any] | None) -> dict[str, Any]:
    bundle = prepared_bundle or {}
    direct = bundle.get("versioning") or {}
    if isinstance(direct, dict) and direct:
        return direct
    prepared_task = bundle.get("prepared_task") or {}
    fallback = prepared_task.get("versioning") or {}
    return fallback if isinstance(fallback, dict) else {}


def _governance_metadata_conflicts_block_approval_on_enforce(
    *,
    bundle_json: str | None = None,
    bundle: dict[str, Any] | None = None,
    log_context: str = "record_approval_preflight",
) -> bool:
    """
    When ATP_GOVERNANCE_AGENT_ENFORCE on AWS, return True if callback metadata is contradictory
    (so approval must not be recorded).
    """
    try:
        from app.core.environment import getRuntimeEnv
        from app.services.agent_execution_policy import (
            log_governance_classification_conflict,
            validate_governance_classification_inputs,
        )
        from app.services.governance_agent_bridge import governance_agent_enforce_production

        if not governance_agent_enforce_production():
            return False
        resolved: dict[str, Any] | None = bundle
        if resolved is None and (bundle_json or "").strip():
            resolved = _deserialize_prepared_bundle(bundle_json)
        if not resolved:
            return False
        cb = resolved.get("callback_selection") or {}
        v = validate_governance_classification_inputs(cb)
        if not v.is_conflicting:
            return False
        log_governance_classification_conflict(
            validation=v,
            selection_reason=str(cb.get("selection_reason") or ""),
            callback_module=str(v.details.get("callback_module") or ""),
            callback_name=str(v.details.get("callback_name") or ""),
            enforcement_active=True,
            environment=getRuntimeEnv(),
            log_context=log_context,
            resolution="blocked_record_approval",
        )
        return True
    except Exception as e:
        logger.warning("_governance_metadata_conflicts_block_approval_on_enforce failed: %s", e)
        return False


def _format_what_will_happen(selection_reason: str, callback_selection: dict[str, Any] | None) -> str:
    """Turn selection_reason into a short one-liner: what will happen if the user approves."""
    reason = (selection_reason or "").strip().lower()
    if not reason or reason == "(none)":
        return "The agent will run the selected callback (apply/validate) for this task."
    if "bug investigation" in reason or "bug_investigation" in reason:
        return "The agent will run a bug investigation and write a structured note to docs/agents/bug-investigations (no code changes)."
    if "documentation" in reason or "generated-notes" in reason:
        return "The agent will generate or update a documentation note under docs/agents/generated-notes."
    if "monitoring triage" in reason or "triage" in reason:
        return "The agent will create a triage note under docs/runbooks/triage (no runtime changes)."
    if "strategy patch" in reason or "strategy-patch" in reason:
        return "The agent will apply a manual-only strategy patch (low-risk business-logic change) after you approve."
    if "profile-setting" in reason or "profile setting" in reason:
        return "The agent will run profile-setting analysis; outcome is a proposal (no automatic change)."
    if "analysis" in reason and "patch" not in reason:
        return "The agent will run an analysis callback and produce a proposal (no automatic code change)."
    # Fallback: use first sentence or first 180 chars of selection_reason
    first_line = (selection_reason or "").strip().split("\n")[0].strip()
    if len(first_line) > 180:
        return first_line[:177] + "..."
    return first_line or "The agent will run the selected callback for this task."


def _format_task_type_label(selection_reason: str) -> str:
    """Short label for task/callback type for the approval card."""
    reason = (selection_reason or "").strip().lower()
    if not reason or reason == "(none)":
        return "Agent task"
    if "bug investigation" in reason or "bug_investigation" in reason:
        return "Bug investigation (docs only)"
    if "documentation" in reason:
        return "Documentation"
    if "monitoring triage" in reason or "triage" in reason:
        return "Monitoring triage"
    if "strategy patch" in reason or "strategy-patch" in reason:
        return "Strategy patch (manual-only)"
    if "profile-setting" in reason:
        return "Profile-setting analysis"
    if "analysis" in reason:
        return "Analysis (proposal only)"
    return "Agent task"


def send_task_approval_request(
    prepared_bundle: dict[str, Any],
    chat_id: str | None = None,
) -> dict[str, Any]:
    """
    Build a Telegram message from the approval summary and task metadata, send it with
    Approve / Deny / View Summary buttons, and store the bundle for later decision.

    NOTE: Approval is triggered ONLY when task reaches ready-for-patch (single trigger point).
    The scheduler no longer calls this at intake; it runs execution directly.
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

    # Quiet mode: only deploy and critical go to Telegram; do not send initial approval request
    try:
        from app.services.agent_telegram_policy import is_quiet_mode
        if is_quiet_mode():
            logger.info("send_task_approval_request: suppressed (quiet mode) task_id=%s", task_id[:12] if task_id else "?")
            return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None, "summary": "quiet mode: not sent"}
    except Exception:
        pass

    # AWS + agent enforce: ensure governance_tasks row early so timeline APIs and visibility emissions
    # can correlate before manifest creation or classification gates (no manifest, no approval).
    try:
        from app.database import SessionLocal
        from app.services.governance_agent_bridge import (
            ensure_notion_governance_task_stub,
            governance_agent_enforce_production,
            infer_governance_risk_for_notion_agent,
        )

        if governance_agent_enforce_production():
            prepared_pt0 = (prepared_bundle or {}).get("prepared_task") or {}
            g_risk0 = infer_governance_risk_for_notion_agent(
                task=prepared_pt0.get("task") or {},
                repo_area=prepared_pt0.get("repo_area") or {},
                sections=prepared_pt0.get("_openclaw_sections") or {},
            )
            gdb_early = SessionLocal()
            if gdb_early is not None:
                try:
                    ensure_notion_governance_task_stub(
                        gdb_early,
                        task_id,
                        title=title,
                        risk_level=g_risk0,
                        actor_id="telegram_approval_request",
                    )
                    gdb_early.commit()
                except Exception as _early_gov_e:
                    logger.warning(
                        "send_task_approval_request: early governance task stub failed task_id=%s err=%s",
                        task_id[:12] if task_id else "?",
                        _early_gov_e,
                    )
                    try:
                        gdb_early.rollback()
                    except Exception:
                        pass
                finally:
                    try:
                        gdb_early.close()
                    except Exception:
                        pass
    except Exception:
        logger.debug("send_task_approval_request: early governance stub skipped", exc_info=True)

    # Block Telegram send on AWS + agent enforce when callback metadata is self-contradictory.
    try:
        from app.core.environment import getRuntimeEnv
        from app.services.agent_execution_policy import (
            log_governance_classification_conflict,
            validate_governance_classification_inputs,
        )
        from app.services.governance_agent_bridge import governance_agent_enforce_production

        if governance_agent_enforce_production():
            _v = validate_governance_classification_inputs(callback_selection)
            if _v.is_conflicting:
                log_governance_classification_conflict(
                    validation=_v,
                    selection_reason=selection_reason,
                    callback_module=str(_v.details.get("callback_module") or ""),
                    callback_name=str(_v.details.get("callback_name") or ""),
                    enforcement_active=True,
                    environment=getRuntimeEnv(),
                    log_context="send_task_approval_request_preflight",
                    resolution="blocked_send_task_approval",
                )
                return {
                    "sent": False,
                    "chat_id": target_chat,
                    "task_id": task_id,
                    "message_id": None,
                    "summary": "governance_classification_conflict",
                }
    except Exception as _preflight_err:
        logger.warning(
            "send_task_approval_request: classification preflight failed task_id=%s err=%s",
            task_id[:12] if task_id else "?",
            _preflight_err,
        )

    # Build message (structured format for clarity)
    rl = (risk_level or "").strip().lower()
    if "high" in rl:
        risk_class = RISK_HIGH
    elif "low" in rl:
        risk_class = RISK_LOW
    else:
        risk_class = RISK_MEDIUM

    likely_files = list(repo_area.get("likely_files") or [])[:8]
    affected_files = list((versioning or {}).get("affected_files") or [])[:8] or likely_files
    files_block = "\n".join(f"• {f}" for f in affected_files) if affected_files else "(inferred from area)"
    scope = f"{len(affected_files)} file(s)" if affected_files else "scope in area"

    proposed = (change_summary or "").strip()[:200] or "(see below)"
    benefits = (change_summary or "").strip()[:150] or "Addresses task requirements"
    risks = f"Standard execution risk ({risk_class} classification)"

    # One-line "what happens if you approve" so user sees it first
    what_will_happen = _format_what_will_happen(selection_reason, callback_selection)
    task_type_label = _format_task_type_label(selection_reason)

    summary_pre = (approval_summary or "").replace("<", "&lt;")[:1200].strip() or "No summary."
    lines = [
        "<b>🔐 Agent task approval</b>",
        "",
        f"<b>📌 IF YOU APPROVE</b>\n{what_will_happen}",
        "",
        f"<b>TASK</b>\n{title[:200]}",
        f"<b>Type:</b> {task_type_label}",
        f"<b>Area:</b> {area_name}",
        "",
        f"<b>WHAT CHANGES</b>\n{proposed}",
        "",
        f"<b>FILES</b>\n{files_block}",
        "",
        f"<b>RISK</b> {risk_class} · {scope}",
        "",
        "<b>ACTION</b> Approve to run, or Deny to stop. Use «View Summary» for full details.",
        "",
        "<b>Full summary</b>",
        "<pre>" + summary_pre + "</pre>",
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
    try:
        _meta = json.loads(bundle_json)
        if _meta.get("bundle_fingerprint"):
            prepared_bundle["bundle_fingerprint_approved"] = _meta["bundle_fingerprint"]
        if isinstance(_meta.get("bundle_identity"), dict):
            prepared_bundle["bundle_identity_approved"] = _meta["bundle_identity"]
    except Exception:
        pass

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

    # AWS + ATP_GOVERNANCE_AGENT_ENFORCE: bind prod_mutation execution approval to a governance manifest.
    try:
        from app.services.agent_execution_policy import (
            ActionClass,
            GovernanceClassificationConflictError,
            classify_callback_action,
        )
        from app.services.governance_agent_bridge import (
            ensure_agent_execute_prepared_manifest,
            governance_agent_enforce_production,
            notion_to_governance_task_id,
        )

        if governance_agent_enforce_production():
            prepared_pt = prepared_bundle.get("prepared_task") or {}
            try:
                _action_cls = classify_callback_action(
                    callback_selection, prepared_pt, log_context="send_task_approval_request"
                )
            except GovernanceClassificationConflictError as _gce:
                logger.error(
                    "send_task_approval_request BLOCKED task_id=%s governance_classification_conflict type=%s",
                    task_id[:12] if task_id else "?",
                    _gce.conflict_type,
                )
                return {
                    "sent": False,
                    "chat_id": target_chat,
                    "task_id": task_id,
                    "message_id": None,
                    "summary": "governance_classification_conflict",
                }
            if _action_cls == ActionClass.PROD_MUTATION:
                from app.database import SessionLocal

                gdb = SessionLocal()
                if gdb is None:
                    logger.error(
                        "send_task_approval_request BLOCKED task_id=%s reason=governance_db_unavailable",
                        task_id[:12] if task_id else "?",
                    )
                    return {
                        "sent": False,
                        "chat_id": target_chat,
                        "task_id": task_id,
                        "message_id": None,
                        "summary": "governance_db_unavailable",
                    }
                try:
                    _mid = ensure_agent_execute_prepared_manifest(
                        gdb,
                        task_id,
                        prepared_task=prepared_pt,
                        callback_selection=callback_selection,
                        title=title,
                        task=(prepared_pt.get("task") or {}),
                        repo_area=prepared_pt.get("repo_area") or {},
                        sections=(prepared_pt.get("_openclaw_sections") or {}),
                    )
                    if not _mid:
                        gdb.rollback()
                        logger.error(
                            "send_task_approval_request BLOCKED task_id=%s reason=governance_execute_manifest_failed",
                            task_id[:12] if task_id else "?",
                        )
                        return {
                            "sent": False,
                            "chat_id": target_chat,
                            "task_id": task_id,
                            "message_id": None,
                            "summary": "governance_execute_manifest_failed",
                        }
                    gdb.commit()
                    from app.services.governance_refs import agent_approval_governance_note_lines

                    gov_note = agent_approval_governance_note_lines(
                        governance_task_id=notion_to_governance_task_id(task_id),
                        notion_page_id=task_id,
                        manifest_id=_mid,
                    )
                    idx = max(0, len(lines) - 2)
                    lines[idx:idx] = gov_note
                    text = "\n".join(lines)
                    if len(text) > TELEGRAM_TEXT_LIMIT:
                        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."
                except Exception as _ge:
                    logger.exception(
                        "send_task_approval_request governance ensure failed task_id=%s",
                        task_id[:12] if task_id else "?",
                    )
                    gdb.rollback()
                    return {
                        "sent": False,
                        "chat_id": target_chat,
                        "task_id": task_id,
                        "message_id": None,
                        "summary": "governance_execute_manifest_failed",
                    }
                finally:
                    try:
                        gdb.close()
                    except Exception:
                        pass
    except Exception as _imp_err:
        logger.exception(
            "send_task_approval_request governance import failed task_id=%s err=%s",
            task_id[:12] if task_id else "?",
            _imp_err,
        )
        return {
            "sent": False,
            "chat_id": target_chat,
            "task_id": task_id,
            "message_id": None,
            "summary": "governance_import_failed",
        }

    # Cache in memory for same-process fast path
    with _STORE_LOCK:
        _APPROVAL_STORE[task_id] = {
            "prepared_bundle": prepared_bundle,
            "status": "pending",
            "requested_at": requested_at_iso,
            "approved_by": "",
            "decision_at": "",
        }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup, message_type="TASK")
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


def clear_task_approval_record(task_id: str) -> bool:
    """Clear the approval record for a task so it can be re-picked by the scheduler.
    Used when task moves to needs-revision (re-investigate flow).
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return False
    db = _get_db_session()
    if db is not None:
        try:
            from app.models.agent_approval_state import AgentApprovalState
            deleted = db.query(AgentApprovalState).filter_by(task_id=task_id).delete()
            db.commit()
            with _STORE_LOCK:
                _APPROVAL_STORE.pop(task_id, None)
            return deleted > 0
        except Exception as e:
            logger.warning("agent_telegram_approval: clear_task_approval_record failed %s", e)
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
    with _STORE_LOCK:
        if task_id in _APPROVAL_STORE:
            del _APPROVAL_STORE[task_id]
            return True
    return False


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
                if _governance_metadata_conflicts_block_approval_on_enforce(
                    bundle_json=row.prepared_bundle_json,
                    log_context="record_approval_db_preflight",
                ):
                    return False
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
            if _governance_metadata_conflicts_block_approval_on_enforce(
                bundle=entry.get("prepared_bundle"),
                log_context="record_approval_memory_preflight",
            ):
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
            # AWS + agent enforce: Telegram Approve must approve the execution manifest digest too.
            try:
                from app.services.agent_execution_policy import (
                    ActionClass,
                    GovernanceClassificationConflictError,
                    classify_callback_action,
                )
                from app.services.governance_agent_bridge import (
                    get_execute_manifest_id,
                    governance_agent_enforce_production,
                )
                from app.services.governance_service import approve_manifest

                _cls_approve = None
                if governance_agent_enforce_production() and prepared_bundle:
                    try:
                        _cls_approve = classify_callback_action(
                            prepared_bundle.get("callback_selection") or {},
                            prepared_bundle.get("prepared_task") or {},
                            log_context="record_approval",
                        )
                    except GovernanceClassificationConflictError as _gce_ra:
                        logger.error(
                            "record_approval: governance_classification_conflict after commit task_id=%s type=%s",
                            task_id[:12] if task_id else "?",
                            _gce_ra.conflict_type,
                        )

                if (
                    governance_agent_enforce_production()
                    and prepared_bundle
                    and _cls_approve == ActionClass.PROD_MUTATION
                ):
                    from app.database import SessionLocal

                    gdb = SessionLocal()
                    if gdb is None:
                        logger.error(
                            "record_approval: governance DB unavailable task_id=%s",
                            task_id[:12] if task_id else "?",
                        )
                    else:
                        try:
                            mid = get_execute_manifest_id(gdb, task_id)
                            if mid:
                                approve_manifest(
                                    gdb,
                                    manifest_id=mid,
                                    approved_by=who,
                                    actor_type="human",
                                    actor_id=who,
                                    environment="prod",
                                )
                                gdb.commit()
                            else:
                                logger.warning(
                                    "record_approval: no execution manifest id (enforce on) task_id=%s",
                                    task_id[:12] if task_id else "?",
                                )
                                gdb.rollback()
                        except Exception as ge:
                            logger.warning("record_approval: approve_manifest failed %s", ge)
                            gdb.rollback()
                        finally:
                            try:
                                gdb.close()
                            except Exception:
                                pass
            except Exception as ge:
                logger.warning("record_approval: governance execution manifest approve block failed %s", ge)
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
                task_type_label = "Task"
                if row.prepared_bundle_json:
                    try:
                        data = json.loads(row.prepared_bundle_json)
                        pt = data.get("prepared_task") or {}
                        task_obj = pt.get("task") or {}
                        task_title = str(task_obj.get("task") or "").strip() or "(no title)"
                        sel = str(data.get("selection_reason") or "").strip()
                        task_type_label = _format_task_type_label(sel)
                    except Exception:
                        pass
                requested_at = ""
                if row.requested_at is not None:
                    requested_at = row.requested_at.isoformat() if hasattr(row.requested_at, "isoformat") else str(row.requested_at)
                results.append({
                    "task_id": row.task_id,
                    "task_title": task_title,
                    "task_type_label": task_type_label,
                    "requested_at": requested_at,
                })
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
            pt = bundle.get("prepared_task") or {}
            task = pt.get("task") or {}
            cs = bundle.get("callback_selection") or {}
            sel = str(cs.get("selection_reason") or "").strip()
            results.append(
                {
                    "task_id": task_id,
                    "task_title": str(task.get("task") or "").strip() or "(no title)",
                    "task_type_label": _format_task_type_label(sel),
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
            sel_reason = str(cs.get("selection_reason") or "").strip()
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
                "selection_reason": sel_reason,
                "what_will_happen": _format_what_will_happen(sel_reason, cs),
                "task_type_label": _format_task_type_label(sel_reason),
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
        sel_reason = out.get("selection_reason") or ""
        out["what_will_happen"] = _format_what_will_happen(sel_reason, None)
        out["task_type_label"] = _format_task_type_label(sel_reason)
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
                bundle = _deserialize_prepared_bundle(row.prepared_bundle_json, execution_load=True)
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
# Risk classification (LOW / MEDIUM / HIGH)
# ---------------------------------------------------------------------------

RISK_LOW = "LOW"
RISK_MEDIUM = "MEDIUM"
RISK_HIGH = "HIGH"


def infer_risk_classification(
    sections: dict[str, Any] | None = None,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> str:
    """
    Infer risk level from OpenClaw sections, task metadata, and repo area.
    Returns LOW, MEDIUM, or HIGH. Conservative when uncertain.
    """
    sections = sections or {}
    task = task or {}
    repo_area = repo_area or {}

    # 1. OpenClaw Risk Level section (if present and parseable)
    risk_raw = sections.get("Risk Level")
    if risk_raw and str(risk_raw).strip().lower() not in ("", "n/a"):
        first_line = str(risk_raw).strip().splitlines()[0].lower()
        if "high" in first_line or "critical" in first_line:
            return RISK_HIGH
        if "medium" in first_line or "moderate" in first_line:
            return RISK_MEDIUM
        if "low" in first_line or "minimal" in first_line:
            return RISK_LOW

    # 2. Task type and area heuristics
    task_type = str(task.get("type") or "").lower()
    project = str(task.get("project") or "").lower()
    details = str(task.get("details") or "").lower()
    area_name = str(repo_area.get("area_name") or "").lower()
    matched_rules = " ".join(str(r).lower() for r in (repo_area.get("matched_rules") or []))
    blob = f"{task_type} {project} {details} {area_name} {matched_rules}"

    high_signals = (
        "deploy", "docker", "nginx", "infra", "runtime", "config",
        "order", "trade", "exchange", "signal", "strategy",
        "telegram_commands", "crypto",
    )
    if any(s in blob for s in high_signals):
        return RISK_HIGH

    medium_signals = (
        "monitor", "health", "sync", "api", "backend",
    )
    if any(s in blob for s in medium_signals):
        return RISK_MEDIUM

    # 3. Affected files: deploy/execution logic
    affected = sections.get("Affected Files") or sections.get("Affected Components") or ""
    affected_lower = str(affected).lower()
    if any(x in affected_lower for x in ("deploy", "docker-compose", "workflow", "github", ".yml", "nginx")):
        return RISK_HIGH

    return RISK_MEDIUM  # Conservative default


# ---------------------------------------------------------------------------
# Extended lifecycle: investigation-complete / patch-deploy approval messages
# ---------------------------------------------------------------------------


def _section_text(sections: dict[str, Any], key: str, max_len: int = 300) -> str:
    """Extract section value, trimmed. Returns placeholder if missing."""
    raw = sections.get(key)
    if raw is None:
        return "(not available)"
    text = str(raw).strip()
    if text.lower() in ("", "n/a"):
        return "(not available)"
    return text[:max_len] + ("…" if len(text) > max_len else "")


def _files_from_sections(sections: dict[str, Any], max_items: int = 8) -> list[str]:
    """Extract file paths from Affected Files section."""
    raw = sections.get("Affected Files") or sections.get("Affected Components")
    if not raw or str(raw).strip().lower() in ("", "n/a"):
        return []
    lines = [l.strip().lstrip("-*•` ").rstrip("` ") for l in str(raw).splitlines() if l.strip()]
    files = [l for l in lines if "/" in l or l.endswith((".py", ".ts", ".tsx", ".yml", ".yaml", ".md"))]
    return files[:max_items]


def _scope_summary(sections: dict[str, Any], files: list[str]) -> str:
    """Short scope description: file count or rough size."""
    if files:
        return f"{len(files)} file(s)"
    affected = sections.get("Affected Components") or sections.get("Affected Files")
    if affected and str(affected).strip().lower() not in ("", "n/a"):
        return "scope in report"
    return "(unknown)"


def format_openclaw_summary_for_telegram(sections: dict[str, Any]) -> str:
    """Build a short HTML-formatted Telegram summary from OpenClaw structured sections.

    Extracts Task Summary, Risk Level, Affected Files, and Recommended Fix.
    When no structured sections are found, falls back to _preamble (raw content
    before any ## headings) so free-form OpenClaw responses still show useful detail.
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
        # Fallback: use _preamble when OpenClaw returns content without section headers
        preamble = sections.get("_preamble")
        if preamble and str(preamble).strip():
            text = str(preamble).strip()
            return f"<b>Investigation:</b>\n{text[:800]}{'…' if len(text) > 800 else ''}"
        return "<i>(no structured report available)</i>"
    return "\n\n".join(parts)


def _preamble_fallback(sections: dict[str, Any], max_len: int = 300) -> str:
    """Use _preamble when structured sections are empty (OpenClaw free-form response)."""
    preamble = sections.get("_preamble")
    if preamble and str(preamble).strip():
        text = str(preamble).strip()
        return text[:max_len] + ("…" if len(text) > max_len else "")
    return "(not available)"


def build_investigation_info_message(
    task_id: str,
    title: str,
    sections: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> str:
    """Build an informational investigation-complete message (no approval requested)."""
    task = task or {}
    repo_area = repo_area or {}

    risk = infer_risk_classification(sections=sections, task=task, repo_area=repo_area)
    root_cause = _section_text(sections, "Root Cause", max_len=180)
    if root_cause == "(not available)":
        root_cause = _preamble_fallback(sections, max_len=180)
    proposed = _section_text(sections, "Recommended Fix", max_len=200)
    if proposed == "(not available)":
        proposed = _preamble_fallback(sections, max_len=200)
    files = _files_from_sections(sections)
    files_block = "\n".join(f"• {f}" for f in files) if files else "(not available)"
    scope = _scope_summary(sections, files)

    # Benefits: infer from Recommended Fix or Task Summary
    benefits_raw = _section_text(sections, "Task Summary", max_len=120)
    if benefits_raw == "(not available)":
        benefits_raw = _preamble_fallback(sections, max_len=120)
    if benefits_raw == "(not available)":
        benefits_raw = "(see proposed change)"
    benefits = benefits_raw

    lines = [
        f"<b>{MSG_PREFIX_INFO}</b> — Investigation complete",
        "",
        f"<b>TASK</b>\n{title[:200]}",
        "",
        f"<b>ROOT CAUSE</b>\n{root_cause}",
        "",
        f"<b>PROPOSED CHANGE</b>\n{proposed}",
        "",
        f"<b>FILES AFFECTED</b>\n{files_block}",
        "",
        f"<b>BENEFITS</b>\n{benefits}",
        "",
        f"<b>SCOPE</b> {scope} · <b>RISK</b> {risk}",
        "",
        "<i>Patch implementation will proceed automatically. Approval required only when patch is ready to deploy.</i>",
    ]
    return "\n".join(lines)


def build_investigation_approval_message(
    task_id: str,
    title: str,
    sections: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> str:
    """Build a concise investigation approval message with all required fields (legacy)."""
    task = task or {}
    repo_area = repo_area or {}

    risk = infer_risk_classification(sections=sections, task=task, repo_area=repo_area)
    root_cause = _section_text(sections, "Root Cause", max_len=180)
    if root_cause == "(not available)":
        root_cause = _preamble_fallback(sections, max_len=180)
    proposed = _section_text(sections, "Recommended Fix", max_len=200)
    if proposed == "(not available)":
        proposed = _preamble_fallback(sections, max_len=200)
    files = _files_from_sections(sections)
    files_block = "\n".join(f"• {f}" for f in files) if files else "(not available)"
    scope = _scope_summary(sections, files)

    # Benefits: infer from Recommended Fix or Task Summary
    benefits_raw = _section_text(sections, "Task Summary", max_len=120)
    if benefits_raw == "(not available)":
        benefits_raw = _preamble_fallback(sections, max_len=120)
    if benefits_raw == "(not available)":
        benefits_raw = "(see proposed change)"
    benefits = benefits_raw

    # Risks: from Risk Level or conservative placeholder
    risks_raw = sections.get("Risk Level")
    if risks_raw and str(risks_raw).strip().lower() not in ("", "n/a"):
        risks = str(risks_raw).strip().splitlines()[0][:150]
    else:
        risks = f"Standard implementation risk ({risk} classification)"

    lines = [
        "<b>🔍 Investigation complete — approve implementation</b>",
        "",
        f"<b>TASK</b>\n{title[:200]}",
        "",
        f"<b>ROOT CAUSE</b>\n{root_cause}",
        "",
        f"<b>PROPOSED CHANGE</b>\n{proposed}",
        "",
        f"<b>FILES AFFECTED</b>\n{files_block}",
        "",
        f"<b>BENEFITS</b>\n{benefits}",
        "",
        f"<b>RISKS</b>\n{risks}",
        "",
        f"<b>SCOPE</b> {scope}",
        "",
        f"<b>RISK CLASSIFICATION</b> {risk}",
        "",
        "<b>ACTION REQUESTED</b>\nApprove to proceed with patch implementation, or Reject to stop.",
    ]
    return "\n".join(lines)


def _parse_md_sections(md_content: str) -> dict[str, str]:
    """Extract ## Section Name -> content from markdown. Used when sidecar has only _preamble."""
    sections: dict[str, str] = {}
    # Use main content: after frontmatter (---...---) if present; else pick part with most ## sections
    parts = md_content.split("---")
    if len(parts) >= 3:
        body = parts[2].strip()  # YAML frontmatter: ---...---\ncontent
    elif len(parts) == 2:
        body = max(parts, key=lambda p: p.count("\n## ")).strip()
    else:
        body = (parts[0] if parts else "").strip()
    if not body:
        return sections
    # Match ## Section Name followed by content until next ## or end
    pattern = re.compile(r"^##\s+(.+?)\s*$", re.MULTILINE)
    matches = list(pattern.finditer(body))
    for i, m in enumerate(matches):
        name = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        content = body[start:end].strip()
        if content and name.lower() not in ("", "n/a"):
            sections[name] = content
    return sections


def _sections_have_required(sections: dict[str, Any]) -> bool:
    """True if sections contain all required keys for deploy approval."""
    return all(
        sections.get(k) and str(sections.get(k)).strip().lower() not in ("", "n/a")
        for k in _REQUIRED_DEPLOY_SECTIONS
    )


def _is_legacy_artifact(source: str | None) -> bool:
    """True if artifact is legacy/backfilled — markdown fallback is allowed when incomplete."""
    if not source:
        return True
    return "backfill" in source.lower()


def _load_sections_from_disk(task_id: str) -> tuple[dict[str, Any], str | None]:
    """Load sections from .sections.json. Returns (sections, source).

    For legacy artifacts (source contains 'backfill'), incomplete sections may be
    supplemented from .md. For new artifacts (source 'openclaw' or 'fallback'),
    incomplete sections are NOT supplemented — caller must block deploy.
    """
    try:
        from pathlib import Path
        from app.services._paths import workspace_root, get_writable_bug_investigations_dir
        repo_root = workspace_root()
        for d in (
            get_writable_bug_investigations_dir(),
            repo_root / "docs" / "agents" / "telegram-alerts",
            repo_root / "docs" / "agents" / "execution-state",
            repo_root / "docs" / "agents" / "generated-notes",
            repo_root / "docs" / "runbooks" / "triage",
        ):
            for f in d.glob(f"*-{task_id}.sections.json"):
                data = json.loads(f.read_text(encoding="utf-8"))
                sections = dict(data.get("sections") or {})
                source = data.get("source") or ""
                if _sections_have_required(sections):
                    return sections, source
                # Incomplete: only use markdown fallback for legacy artifacts
                if _is_legacy_artifact(source):
                    logger.warning(
                        "sections_json_incomplete_fallback_used task_id=%s path=%s source=%s legacy=true — "
                        "parsing .md for legacy artifact",
                        task_id[:12] if task_id else "?", f, source,
                    )
                    md_path = d / f.name.replace(".sections.json", ".md")
                    if md_path.exists():
                        raw = md_path.read_text(encoding="utf-8")
                        parsed = _parse_md_sections(raw)
                        for k, v in parsed.items():
                            if k not in sections or not (sections.get(k) and str(sections.get(k)).strip()):
                                sections[k] = v
                return sections, source
            for prefix in ("notion-bug", "notion-telegram", "notion-execution", "notion-task"):
                md_path = d / f"{prefix}-{task_id}.md"
                if md_path.exists():
                    raw = md_path.read_text(encoding="utf-8")
                    parts = raw.split("---")
                    body = max(parts, key=lambda p: p.count("\n## ")).strip() if len(parts) >= 2 else (parts[0] if parts else "").strip()
                    if body:
                        return {"_preamble": body}, None
    except Exception as e:
        logger.debug("_load_sections_from_disk failed task_id=%s: %s", task_id, e)
    return {}, None


def _investigation_info_dedup_key(task_id: str) -> str:
    """DB key for investigation-complete dedup. Shared across workers/restarts."""
    return f"{_AGENT_INFO_DEDUP_KEY_PREFIX}{task_id}"


def _get_investigation_info_last_sent_db(task_id: str) -> datetime | None:
    """Read last-sent timestamp from DB. Returns None if not found or on error."""
    try:
        from app.database import SessionLocal
        from app.models.trading_settings import TradingSettings
    except Exception:
        return None
    db = SessionLocal()
    try:
        key = _investigation_info_dedup_key(task_id)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if not row or not row.setting_value:
            return None
        return datetime.fromisoformat(row.setting_value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    except Exception as e:
        logger.debug("agent_telegram_approval: _get_investigation_info_last_sent_db failed: %s", e)
        return None
    finally:
        db.close()


def _set_investigation_info_last_sent_db(task_id: str, ts: datetime) -> None:
    """Write last-sent timestamp to DB."""
    try:
        from app.database import SessionLocal
        from app.models.trading_settings import TradingSettings
    except Exception:
        return
    db = SessionLocal()
    try:
        key = _investigation_info_dedup_key(task_id)
        value = ts.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if row:
            row.setting_value = value
        else:
            db.add(TradingSettings(setting_key=key, setting_value=value))
        db.commit()
    except Exception as e:
        logger.debug("agent_telegram_approval: _set_investigation_info_last_sent_db failed: %s", e)
        db.rollback()
    finally:
        db.close()


def _should_skip_investigation_info_dedup(task_id: str) -> bool:
    """Return True if we already sent investigation info for this task within cooldown.

    Uses DB (TradingSettings) as source of truth. Survives restarts and shared across workers.
    JSONL/agent_activity is no longer used for dedup (logging only).
    """
    from datetime import timedelta

    key = _investigation_info_dedup_key(task_id)
    now = datetime.now(timezone.utc)
    last_sent = _get_investigation_info_last_sent_db(task_id)

    if last_sent is None:
        logger.info(
            "investigation_info_dedup task_id=%s dedup_key=%s decision=allowed reason=no_previous_send",
            task_id, key,
        )
        return False

    cooldown = timedelta(hours=_INVESTIGATION_INFO_DEDUP_HOURS)
    hours_ago = (now - last_sent).total_seconds() / 3600

    if now - last_sent >= cooldown:
        logger.info(
            "investigation_info_dedup task_id=%s dedup_key=%s last_sent=%s decision=allowed reason=cooldown_elapsed hours_ago=%.1f",
            task_id, key, last_sent.isoformat(), hours_ago,
        )
        return False

    logger.info(
        "investigation_info_dedup task_id=%s dedup_key=%s last_sent=%s decision=skipped reason=within_cooldown hours_ago=%.1f cooldown_h=%d",
        task_id, key, last_sent.isoformat(), hours_ago, _INVESTIGATION_INFO_DEDUP_HOURS,
    )
    return True


def send_investigation_complete_info(
    task_id: str,
    title: str,
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Send an informational Telegram message after OpenClaw investigation completes.

    No approval requested — informational only. Patch implementation proceeds
    automatically; approval is required only when patch is ready to deploy.

    Returns ``{"sent": bool, "chat_id": str, "task_id": str, "message_id": int | None}``.
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    try:
        from app.services.agent_telegram_policy import is_quiet_mode
        if is_quiet_mode():
            logger.info("send_investigation_complete_info: suppressed (quiet mode) task_id=%s", task_id[:12] if task_id else "?")
            return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None}
    except Exception:
        pass

    if _should_skip_investigation_info_dedup(task_id):
        return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None, "skipped": "dedup"}

    sections = sections or {}
    if not sections or not any(
        sections.get(k) and str(sections.get(k)).strip().lower() not in ("", "n/a")
        for k in ("Task Summary", "Root Cause", "Recommended Fix", "_preamble")
    ):
        disk_sections, _ = _load_sections_from_disk(task_id)
        if disk_sections:
            sections = disk_sections
    with _STORE_LOCK:
        _SECTIONS_CACHE[task_id] = sections

    text = build_investigation_info_message(
        task_id, title, sections, task=task, repo_area=repo_area,
    )
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    # Informational only — no approval buttons. Optional View Report in verbose mode.
    reply_markup = None
    if _get_notification_mode() == "verbose":
        reply_markup = {
            "inline_keyboard": [
                [{"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"}],
            ]
        }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup, message_type="INVESTIGATION")
    if sent:
        _set_investigation_info_last_sent_db(task_id, datetime.now(timezone.utc))
        logger.info(
            "investigation_info_dedup task_id=%s dedup_key=%s decision=sent message_id=%s (recorded to DB)",
            task_id, _investigation_info_dedup_key(task_id), message_id,
        )
    else:
        logger.info(
            "send_investigation_complete_info task_id=%s sent=False message_id=%s",
            task_id, message_id,
        )

    # Operational logging only (JSONL); no longer used for dedup
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "investigation_info_sent",
            task_id=task_id,
            task_title=title,
            details={"chat_id": target_chat, "sent": sent, "message_id": message_id},
        )
    except Exception:
        pass

    return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id}


def send_investigation_complete_approval(
    task_id: str,
    title: str,
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DISABLED: Single-approval workflow — no approval at investigation-complete."""
    task_id = (task_id or "").strip()
    logger.info(
        "send_investigation_complete_approval: disabled (single-approval workflow) task_id=%s",
        task_id[:12] if task_id else "?",
    )
    return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None, "skipped": "single_approval_workflow"}


def build_release_candidate_approval_message(
    task_id: str,
    title: str,
    test_summary: str,
    sections: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    verification_unavailable_reason: str | None = None,
    proposed_version: str = "",
) -> str:
    """Build the single final approval message when release candidate is ready.

    Includes: version, problems solved, improvements, validation evidence,
    known risks, and clear approve/reject prompt.
    """
    task = task or {}
    proposed_version = (proposed_version or "").strip() or str(task.get("proposed_version") or "").strip()
    if not proposed_version:
        proposed_version = "(e.g. atp.3.4)"

    risk = infer_risk_classification(sections=sections, task=task, repo_area=repo_area)
    root_cause = _section_text(sections, "Root Cause", max_len=200)
    if root_cause == "(not available)":
        root_cause = _section_text(sections, "Task Summary", max_len=200)
    if root_cause == "(not available)":
        root_cause = _preamble_fallback(sections, max_len=200)
    change_summary = _section_text(sections, "Recommended Fix", max_len=200)
    if change_summary == "(not available)":
        change_summary = _section_text(sections, "Task Summary", max_len=200)
    if change_summary == "(not available)":
        change_summary = _preamble_fallback(sections, max_len=200)
    files = _files_from_sections(sections)
    files_block = "\n".join(f"• {f}" for f in files) if files else "(not available)"
    scope = _scope_summary(sections, files)

    if verification_unavailable_reason:
        validation_evidence = (
            "⚠️ Verification unavailable (environment not configured). "
            "Patch is ready — approval can proceed manually or verification can be skipped."
        )
        if verification_unavailable_reason.strip():
            validation_evidence += f"\n<i>Reason: {verification_unavailable_reason[:150]}</i>"
    else:
        test_status = (test_summary or "").strip()[:400] or "passed"
        if "passed" in test_status.lower() or "ok" in test_status.lower():
            validation_evidence = f"✅ {test_status}"
        else:
            validation_evidence = test_status

    benefits = _section_text(sections, "Task Summary", max_len=120)
    if benefits == "(not available)":
        benefits = _preamble_fallback(sections, max_len=120)
    if benefits == "(not available)":
        benefits = "Addresses task requirements"

    risks_raw = sections.get("Risk Level")
    if risks_raw and str(risks_raw).strip().lower() not in ("", "n/a"):
        risks = str(risks_raw).strip().splitlines()[0][:120]
    else:
        risks = f"Standard deploy risk ({risk} classification)"

    lines = [
        f"<b>{MSG_PREFIX_APPROVAL}</b> — Release candidate ready (single approval)",
        "",
        f"<b>VERSION</b> {proposed_version}",
        "",
        f"<b>TASK</b>\n{title[:200]}",
        "",
        "<b>PROBLEMS SOLVED</b>",
        root_cause,
        "",
        "<b>IMPROVEMENTS</b>",
        change_summary,
        "",
        f"<b>FILES CHANGED</b>\n{files_block}",
        "",
        "<b>VALIDATION EVIDENCE</b>",
        validation_evidence,
        "",
        "<b>KNOWN RISKS / OPEN ISSUES</b>",
        risks,
        "",
        f"<b>SCOPE</b> {scope} · <b>RISK</b> {risk}",
        "",
        "<b>APPROVE or REJECT?</b>",
        "Tap <b>Approve Deploy</b> to deploy, or <b>Reject</b> to stop. <b>Smoke Check</b> for pre-deploy verification.",
    ]
    return "\n".join(lines)


def build_deploy_approval_message(
    task_id: str,
    title: str,
    test_summary: str,
    sections: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    verification_unavailable_reason: str | None = None,
) -> str:
    """Build a concise deploy approval message with all required fields."""
    task = task or {}
    repo_area = repo_area or {}

    risk = infer_risk_classification(sections=sections, task=task, repo_area=repo_area)
    root_cause = _section_text(sections, "Root Cause", max_len=200)
    if root_cause == "(not available)":
        root_cause = _section_text(sections, "Task Summary", max_len=200)
    if root_cause == "(not available)":
        root_cause = _preamble_fallback(sections, max_len=200)
    change_summary = _section_text(sections, "Recommended Fix", max_len=200)
    if change_summary == "(not available)":
        change_summary = _section_text(sections, "Task Summary", max_len=200)
    if change_summary == "(not available)":
        change_summary = _preamble_fallback(sections, max_len=200)
    files = _files_from_sections(sections)
    files_block = "\n".join(f"• {f}" for f in files) if files else "(not available)"
    scope = _scope_summary(sections, files)

    if verification_unavailable_reason:
        test_status_display = (
            "⚠️ Verification unavailable (environment not configured). "
            "Patch is ready — approval can proceed manually or verification can be skipped."
        )
        if verification_unavailable_reason.strip():
            test_status_display += f"\n<i>Reason: {verification_unavailable_reason[:150]}</i>"
    else:
        test_status = (test_summary or "").strip()[:400] or "passed"
        if "passed" in test_status.lower() or "ok" in test_status.lower():
            test_status_display = f"✅ {test_status}"
        else:
            test_status_display = test_status

    benefits = _section_text(sections, "Task Summary", max_len=120)
    if benefits == "(not available)":
        benefits = _preamble_fallback(sections, max_len=120)
    if benefits == "(not available)":
        benefits = "Addresses task requirements"

    risks_raw = sections.get("Risk Level")
    if risks_raw and str(risks_raw).strip().lower() not in ("", "n/a"):
        risks = str(risks_raw).strip().splitlines()[0][:120]
    else:
        risks = f"Standard deploy risk ({risk} classification)"

    if verification_unavailable_reason:
        header = f"<b>{MSG_PREFIX_APPROVAL}</b> — Patch ready (verification unavailable)"
    else:
        header = f"<b>{MSG_PREFIX_APPROVAL}</b> — Patch ready to deploy"
    lines = [
        header,
        "",
        f"<b>TASK</b>\n{title[:200]}",
        "",
        f"<b>ROOT CAUSE</b>\n{root_cause}",
        "",
        f"<b>SOLUTION</b>\n{change_summary}",
        "",
        f"<b>FILES CHANGED</b>\n{files_block}",
        "",
        f"<b>VERIFICATION</b>\n{test_status_display}",
        "",
        f"<b>BENEFITS</b>\n{benefits}",
        "",
        f"<b>RISKS</b>\n{risks}",
        "",
        f"<b>SCOPE</b> {scope} · <b>RISK</b> {risk}",
        "",
        "<b>Do you want to deploy?</b>",
        "Use <b>Approve Deploy</b> to trigger deployment, or <b>Smoke Check</b> first.",
    ]
    return "\n".join(lines)


def _should_skip_ready_for_patch_approval_dedup(task_id: str) -> bool:
    """Return True if we already sent ready-for-patch approval for this task recently (deduplication)."""
    now = time.time()
    cutoff = now - (_DEPLOY_APPROVAL_DEDUP_HOURS * 3600)
    with _STORE_LOCK:
        last_sent = _DEPLOY_APPROVAL_SENT.get(f"ready_for_patch:{task_id}")
        if last_sent and last_sent > cutoff:
            logger.info(
                "send_ready_for_patch_approval: approval_skipped_reason=dedup task_id=%s last_sent=%.0fs ago",
                task_id, now - last_sent,
            )
            return True
    return False


def build_ready_for_patch_approval_message(
    task_id: str,
    title: str,
    sections: dict[str, Any],
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> str:
    """Build approval message when task reaches ready-for-patch (single approval trigger point)."""
    task = task or {}
    repo_area = repo_area or {}

    risk = infer_risk_classification(sections=sections, task=task, repo_area=repo_area)
    root_cause = _section_text(sections, "Root Cause", max_len=200)
    if root_cause == "(not available)":
        root_cause = _section_text(sections, "Task Summary", max_len=200)
    if root_cause == "(not available)":
        root_cause = _preamble_fallback(sections, max_len=200)
    change_summary = _section_text(sections, "Recommended Fix", max_len=200)
    if change_summary == "(not available)":
        change_summary = _section_text(sections, "Task Summary", max_len=200)
    if change_summary == "(not available)":
        change_summary = _preamble_fallback(sections, max_len=200)
    files = _files_from_sections(sections)
    files_block = "\n".join(f"• {f}" for f in files) if files else "(not available)"
    scope = _scope_summary(sections, files)

    benefits = _section_text(sections, "Task Summary", max_len=120)
    if benefits == "(not available)":
        benefits = _preamble_fallback(sections, max_len=120)
    if benefits == "(not available)":
        benefits = "Addresses task requirements"

    risks_raw = sections.get("Risk Level")
    if risks_raw and str(risks_raw).strip().lower() not in ("", "n/a"):
        risks = str(risks_raw).strip().splitlines()[0][:120]
    else:
        risks = f"Standard patch risk ({risk} classification)"

    lines = [
        f"<b>{MSG_PREFIX_APPROVAL}</b> — Patch ready for approval",
        "",
        f"<b>TASK ID</b> <code>{task_id}</code>",
        "",
        f"<b>TASK</b>\n{title[:200]}",
        "",
        f"<b>ROOT CAUSE</b>\n{root_cause}",
        "",
        f"<b>PATCH SUMMARY</b>\n{change_summary}",
        "",
        f"<b>FILES CHANGED</b>\n{files_block}",
        "",
        f"<b>BENEFITS</b>\n{benefits}",
        "",
        f"<b>RISKS</b>\n{risks}",
        "",
        f"<b>SCOPE</b> {scope} · <b>RISK</b> {risk}",
        "",
        "<b>ACTION</b> Approve to apply patch, or Reject to stop.",
    ]
    return "\n".join(lines)


def send_ready_for_patch_approval(
    task_id: str,
    title: str,
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """DISABLED: Single-approval workflow — no intermediate approval at ready-for-patch.

    Approval is sent ONLY when task reaches release-candidate-ready.
    Returns without sending to prevent duplicate approval noise.
    """
    task_id = (task_id or "").strip()
    logger.info(
        "send_ready_for_patch_approval: disabled (single-approval workflow) task_id=%s — "
        "approval only at release-candidate-ready",
        task_id[:12] if task_id else "?",
    )
    return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None, "skipped": "single_approval_workflow"}


def _release_candidate_approval_dedup_key(task_id: str, proposed_version: str) -> str:
    """DB key for release-candidate approval dedup. One approval per task+version."""
    pv = (proposed_version or "").strip() or "_default"
    return f"{_RELEASE_CANDIDATE_DEDUP_KEY_PREFIX}{task_id}:{pv}"


def _check_release_candidate_approval_dedup(task_id: str, proposed_version: str) -> tuple[bool, str]:
    """Check dedup for release-candidate approval. Fail-closed when DB unavailable.

    Returns (block_send, reason):
      (False, "") — proceed (allow send)
      (True, "dedup") — skip (already sent within cooldown or in-memory fallback)
      (True, "dedup_check_unavailable") — block (DB error; fail-closed, do not send)
    """
    from datetime import timedelta

    # In-memory fallback: we sent but DB write failed; block retry within same process
    with _SENT_BUT_DEDUP_WRITE_FAILED_LOCK:
        if (task_id, proposed_version) in _SENT_BUT_DEDUP_WRITE_FAILED:
            logger.info(
                "release_candidate_approval_dedup task_id=%s version=%s skipped reason=in_memory_fallback "
                "(prior send succeeded but dedup DB write failed)",
                task_id[:12] if task_id else "?", (proposed_version or "")[:20],
            )
            return (True, "dedup")

    try:
        last_sent = _get_release_candidate_approval_last_sent_db(task_id, proposed_version)
    except Exception as e:
        logger.warning(
            "release_candidate_approval_dedup BLOCKED task_id=%s version=%s reason=dedup_check_unavailable error=%s",
            task_id[:12] if task_id else "?", (proposed_version or "")[:20], e,
        )
        return (True, "dedup_check_unavailable")

    if last_sent is None:
        return (False, "")

    now = datetime.now(timezone.utc)
    cooldown = timedelta(hours=_RELEASE_CANDIDATE_DEDUP_HOURS)
    if now - last_sent >= cooldown:
        return (False, "")

    hours_ago = (now - last_sent).total_seconds() / 3600
    logger.info(
        "release_candidate_approval_dedup task_id=%s version=%s skipped reason=within_cooldown hours_ago=%.1f",
        task_id[:12] if task_id else "?", (proposed_version or "")[:20], hours_ago,
    )
    return (True, "dedup")


def _get_release_candidate_approval_last_sent_db(task_id: str, proposed_version: str) -> datetime | None:
    """Read last-sent timestamp from DB. Returns None if not found. Raises on DB error (caller fails closed)."""
    from app.database import SessionLocal
    from app.models.trading_settings import TradingSettings

    db = SessionLocal()
    if db is None:
        raise RuntimeError("SessionLocal returned None — DB unavailable")
    try:
        key = _release_candidate_approval_dedup_key(task_id, proposed_version)
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if not row or not row.setting_value:
            return None
        return datetime.fromisoformat(row.setting_value.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    except Exception:
        raise
    finally:
        db.close()


def _set_release_candidate_approval_sent_db(task_id: str, proposed_version: str) -> bool:
    """Write last-sent timestamp to DB. Returns True if persisted, False on failure."""
    try:
        from app.database import SessionLocal
        from app.models.trading_settings import TradingSettings
    except Exception as e:
        logger.warning(
            "release_candidate_approval_dedup_write FAILED task_id=%s version=%s reason=import_error error=%s",
            task_id[:12] if task_id else "?", (proposed_version or "")[:20], e,
        )
        return False

    db = SessionLocal()
    if db is None:
        logger.warning(
            "release_candidate_approval_dedup_write FAILED task_id=%s version=%s reason=session_none",
            task_id[:12] if task_id else "?", (proposed_version or "")[:20],
        )
        return False

    try:
        key = _release_candidate_approval_dedup_key(task_id, proposed_version)
        value = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        row = db.query(TradingSettings).filter(TradingSettings.setting_key == key).first()
        if row:
            row.setting_value = value
        else:
            db.add(TradingSettings(setting_key=key, setting_value=value))
        db.commit()
        return True
    except Exception as e:
        logger.warning(
            "release_candidate_approval_dedup_write FAILED task_id=%s version=%s error=%s — "
            "approval was sent; in-memory fallback will block retry within same process",
            task_id[:12] if task_id else "?", (proposed_version or "")[:20], e,
        )
        db.rollback()
        return False
    finally:
        db.close()


def _should_skip_deploy_approval_dedup(task_id: str) -> bool:
    """Return True if we already sent deploy approval for this task recently (deduplication)."""
    now = time.time()
    cutoff = now - (_DEPLOY_APPROVAL_DEDUP_HOURS * 3600)
    with _STORE_LOCK:
        last_sent = _DEPLOY_APPROVAL_SENT.get(task_id)
        if last_sent and last_sent > cutoff:
            logger.info(
                "send_patch_deploy_approval: skipping duplicate task_id=%s last_sent=%.0fs ago",
                task_id, now - last_sent,
            )
            return True
    return False


def send_release_candidate_approval(
    task_id: str,
    title: str,
    test_summary: str = "",
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    verification_unavailable_reason: str | None = None,
    proposed_version: str = "",
) -> dict[str, Any]:
    """Send the single final approval request when release candidate is ready.

    Called ONLY when task reaches release-candidate-ready (all acceptance checks pass).
    No approval messages during investigation, patching, verifying, or re-iterating.

    Message includes: version, problems solved, improvements, validation evidence,
    known risks, and clear approve/reject prompt.

    Buttons: [Approve Deploy] [Reject] [View Report] [Smoke Check]

    Returns ``{"sent": bool, "chat_id": str, "task_id": str, "message_id": int | None}``.
    """
    return _send_release_candidate_or_deploy_approval(
        task_id=task_id,
        title=title,
        test_summary=test_summary,
        sections=sections,
        chat_id=chat_id,
        task=task,
        repo_area=repo_area,
        verification_unavailable_reason=verification_unavailable_reason,
        proposed_version=proposed_version,
        use_release_candidate_format=True,
    )


def _send_release_candidate_or_deploy_approval(
    task_id: str,
    title: str,
    test_summary: str = "",
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    verification_unavailable_reason: str | None = None,
    proposed_version: str = "",
    use_release_candidate_format: bool = False,
) -> dict[str, Any]:
    """Internal: send approval when release-candidate-ready or (legacy) deploy-ready.

    use_release_candidate_format=True uses build_release_candidate_approval_message.
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    # Release-candidate: mandatory proposed_version; fail-closed when dedup check unavailable
    pv = (proposed_version or "").strip() or str((task or {}).get("proposed_version") or "").strip()
    if use_release_candidate_format:
        if not pv:
            logger.warning(
                "send_release_candidate_approval BLOCKED task_id=%s reason=missing_proposed_version",
                task_id[:12] if task_id else "?",
            )
            return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None, "skipped": "missing_proposed_version"}
        block_send, dedup_reason = _check_release_candidate_approval_dedup(task_id, pv)
        if block_send:
            logger.info(
                "send_release_candidate_approval BLOCKED task_id=%s reason=%s",
                task_id[:12] if task_id else "?", dedup_reason,
            )
            return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None, "skipped": dedup_reason}
    else:
        if _should_skip_deploy_approval_dedup(task_id):
            return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None, "skipped": "dedup"}

    sections = sections or {}
    if sections:
        with _STORE_LOCK:
            _SECTIONS_CACHE[task_id] = sections

    # Load sections from disk when structured content is missing (Root Cause, Recommended Fix, Task Summary).
    # Sidecar may have only _preamble; _load_sections_from_disk parses .md for ## sections.
    has_structured = any(
        sections.get(k) and str(sections.get(k)).strip().lower() not in ("", "n/a")
        for k in ("Task Summary", "Root Cause", "Recommended Fix")
    )
    if not sections or not has_structured:
        disk_sections, disk_source = _load_sections_from_disk(task_id)
        if disk_sections:
            sections = disk_sections
            # New artifacts (openclaw/fallback) must have complete sections — block deploy if incomplete
            if not _sections_have_required(sections) and not _is_legacy_artifact(disk_source):
                logger.error(
                    "sections_json_validation_failed task_id=%s source=%s — "
                    "new artifact missing required sections (Task Summary, Root Cause, Recommended Fix, Affected Files); "
                    "deploy approval blocked",
                    task_id[:12] if task_id else "?", disk_source or "?",
                )
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event(
                        "deploy_blocked_sections_incomplete",
                        task_id=task_id,
                        task_title=title,
                        details={"source": disk_source, "reason": "missing_required_sections"},
                    )
                except Exception:
                    pass
                msg = (
                    f"<b>{MSG_PREFIX_INFO}</b> — Deploy blocked (validation)\n\n"
                    f"<b>TASK</b>\n{title[:200]}\n\n"
                    "<i>Investigation artifact is incomplete. Required sections (Task Summary, Root Cause, "
                    "Recommended Fix, Affected Files) are missing from .sections.json.</i>\n\n"
                    "<i>Re-run investigation or backfill: <code>python scripts/backfill_sections_json.py --write</code></i>"
                )
                if len(msg) > TELEGRAM_TEXT_LIMIT:
                    msg = msg[: TELEGRAM_TEXT_LIMIT - 3] + "..."
                sent, message_id = _send_telegram_message(target_chat, msg, None, message_type="PATCH")
                return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id, "approval_skipped": "validation_failed"}

    # If no valid artifact/report: send concise info instead of approval request
    has_artifact = bool(sections and _sections_have_required(sections))

    if not has_artifact:
        # Send concise info — no approval buttons; approval deferred until artifact available
        msg = (
            f"<b>{MSG_PREFIX_INFO}</b> — Patch validation complete\n\n"
            f"<b>TASK</b>\n{title[:200]}\n\n"
            "<i>No OpenClaw report/artifact cached. Check task notes or docs/agents/bug-investigations.</i>\n\n"
            f"<b>Test status:</b> {str(test_summary or 'passed')[:200]}\n\n"
            "<i>Approval deferred until valid report/artifact is available.</i>"
        )
        if len(msg) > TELEGRAM_TEXT_LIMIT:
            msg = msg[: TELEGRAM_TEXT_LIMIT - 3] + "..."
        sent, message_id = _send_telegram_message(target_chat, msg, None, message_type="PATCH")
        logger.info(
            "send_patch_deploy_approval: sent info (no artifact/test) task_id=%s sent=%s",
            task_id, sent,
        )
        return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id, "approval_skipped": True}

    test_str = (test_summary or "").strip()[:500] or "(no test output)"
    if use_release_candidate_format:
        pv = (proposed_version or "").strip() or (task or {}).get("proposed_version") or ""
        text = build_release_candidate_approval_message(
            task_id, title, test_str,
            sections, task=task, repo_area=repo_area,
            verification_unavailable_reason=verification_unavailable_reason,
            proposed_version=pv,
        )
    else:
        text = build_deploy_approval_message(
            task_id, title, test_str,
            sections, task=task, repo_area=repo_area,
            verification_unavailable_reason=verification_unavailable_reason,
        )

    # AWS + ATP_GOVERNANCE_AGENT_ENFORCE: bind release-candidate Telegram to a governance manifest (digest) before send.
    if use_release_candidate_format:
        try:
            from app.services.governance_agent_bridge import (
                ensure_agent_deploy_manifest,
                governance_agent_enforce_production,
            )
            if governance_agent_enforce_production():
                from app.database import SessionLocal

                _gdb = SessionLocal()
                if _gdb is None:
                    logger.error(
                        "send_release_candidate_approval BLOCKED task_id=%s reason=governance_db_unavailable",
                        task_id[:12] if task_id else "?",
                    )
                    return {
                        "sent": False,
                        "chat_id": target_chat,
                        "task_id": task_id,
                        "message_id": None,
                        "skipped": "governance_db_unavailable",
                    }
                try:
                    _mid = ensure_agent_deploy_manifest(
                        _gdb,
                        task_id,
                        title=title,
                        task=task,
                        repo_area=repo_area,
                        sections=sections,
                    )
                    if not _mid:
                        _gdb.rollback()
                        logger.error(
                            "send_release_candidate_approval BLOCKED task_id=%s reason=governance_manifest_failed",
                            task_id[:12] if task_id else "?",
                        )
                        return {
                            "sent": False,
                            "chat_id": target_chat,
                            "task_id": task_id,
                            "message_id": None,
                            "skipped": "governance_manifest_failed",
                        }
                    _gdb.commit()
                    text = (
                        text
                        + f"\n\n<i>Governance</i> <code>{_mid}</code>\n"
                        "<i>Approve Deploy approves this manifest digest; execution uses governance_executor.</i>"
                    )
                except Exception as _ge:
                    logger.exception(
                        "send_release_candidate_approval governance ensure failed task_id=%s",
                        task_id[:12] if task_id else "?",
                    )
                    _gdb.rollback()
                    return {
                        "sent": False,
                        "chat_id": target_chat,
                        "task_id": task_id,
                        "message_id": None,
                        "skipped": "governance_manifest_failed",
                    }
                finally:
                    try:
                        _gdb.close()
                    except Exception:
                        pass
        except Exception as _imp_err:
            logger.exception(
                "send_release_candidate_approval governance import failed task_id=%s err=%s",
                task_id[:12] if task_id else "?",
                _imp_err,
            )
            return {
                "sent": False,
                "chat_id": target_chat,
                "task_id": task_id,
                "message_id": None,
                "skipped": "governance_import_failed",
            }

    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🚀 Approve Deploy", "callback_data": f"{PREFIX_APPROVE_DEPLOY}{task_id}"},
                {"text": "❌ Reject", "callback_data": f"{PREFIX_REJECT}{task_id}"},
            ],
            [
                {"text": "🔍 Smoke Check", "callback_data": f"{PREFIX_SMOKE_CHECK}{task_id}"},
                {"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"},
            ],
        ]
    }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup, message_type="PATCH")
    dedup_write_failed = False
    if sent:
        with _STORE_LOCK:
            _DEPLOY_APPROVAL_SENT[task_id] = time.time()
        if use_release_candidate_format:
            if not _set_release_candidate_approval_sent_db(task_id, pv):
                dedup_write_failed = True
                with _SENT_BUT_DEDUP_WRITE_FAILED_LOCK:
                    _SENT_BUT_DEDUP_WRITE_FAILED.add((task_id, pv))

    log_fn = "send_release_candidate_approval" if use_release_candidate_format else "send_patch_deploy_approval"
    logger.info(
        "%s task_id=%s sent=%s message_id=%s dedup_write_failed=%s",
        log_fn, task_id, sent, message_id, dedup_write_failed,
    )

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "deploy_approval_sent",
            task_id=task_id,
            task_title=title,
            details={"chat_id": target_chat, "sent": sent, "message_id": message_id, "dedup_write_failed": dedup_write_failed},
        )
    except Exception:
        pass

    result: dict[str, Any] = {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id}
    if dedup_write_failed:
        result["dedup_write_failed"] = True
    return result


def send_patch_deploy_approval(
    task_id: str,
    title: str,
    test_summary: str = "",
    sections: dict[str, Any] | None = None,
    chat_id: str | None = None,
    *,
    task: dict[str, Any] | None = None,
    repo_area: dict[str, Any] | None = None,
    verification_unavailable_reason: str | None = None,
) -> dict[str, Any]:
    """Legacy: send deploy approval. Prefer send_release_candidate_approval for new code."""
    return _send_release_candidate_or_deploy_approval(
        task_id=task_id,
        title=title,
        test_summary=test_summary,
        sections=sections,
        chat_id=chat_id,
        task=task,
        repo_area=repo_area,
        verification_unavailable_reason=verification_unavailable_reason,
        use_release_candidate_format=False,
    )


def send_blocker_notification(
    task_id: str,
    title: str,
    reason: str,
    chat_id: str | None = None,
    *,
    suggested_action: str = "",
) -> dict[str, Any]:
    """Send a Telegram message when a real blocker is reached.

    Clearly marked as BLOCKER (not approval). Use only for real blockers that
    require human intervention. No approval buttons — informational only.
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    reason = (reason or "").strip()[:500]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    lines = [
        f"<b>{MSG_PREFIX_BLOCKER}</b> — Real blocker (not an approval request)",
        "",
        f"<b>TASK</b>\n{title}",
        "",
        "<b>BLOCKER</b>",
        reason,
    ]
    if suggested_action:
        lines.extend(["", "<b>SUGGESTED ACTION</b>", suggested_action[:300]])
    text = "\n".join(lines)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    sent, message_id = _send_telegram_message(target_chat, text, None, message_type="BLOCKER")
    logger.info(
        "send_blocker_notification task_id=%s sent=%s message_id=%s",
        task_id, sent, message_id,
    )
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "blocker_notification_sent",
            task_id=task_id,
            task_title=title,
            details={"reason": reason[:200], "sent": sent},
        )
    except Exception:
        pass
    return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id}


def send_patch_not_applied_message(
    task_id: str,
    title: str,
    chat_id: str | None = None,
) -> dict[str, Any]:
    """Send Telegram message when code-fix task has no patch proof — blocks deploy until Cursor Bridge runs.

    Buttons: [🛠️ Run Cursor Bridge] [📋 View Report]
    No Approve Deploy — patch must be applied first.
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    text = (
        f"<b>⚠️ Patch not yet applied</b> (not an approval request)\n\n"
        f"<b>TASK</b>\n{title}\n\n"
        "This is a <b>code-fix task</b>. Investigation is complete, but no code changes have been applied.\n\n"
        "Deploy is blocked until Cursor Bridge runs and applies the fix. "
        "Tap <b>Run Cursor Bridge</b> to apply the patch and run tests. "
        "You will receive exactly one final approval request when the release candidate is ready."
    )
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    reply_markup = {
        "inline_keyboard": [
            [{"text": "🛠️ Run Cursor Bridge", "callback_data": f"{PREFIX_RUN_CURSOR_BRIDGE}{task_id}"}],
            [{"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"}],
        ]
    }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup, message_type="PATCH")
    logger.info(
        "send_patch_not_applied_message task_id=%s sent=%s message_id=%s",
        task_id, sent, message_id,
    )

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "patch_not_applied_sent",
            task_id=task_id,
            task_title=title,
            details={"chat_id": target_chat, "sent": sent, "message_id": message_id},
        )
    except Exception:
        pass

    return {"sent": sent, "chat_id": target_chat, "task_id": task_id, "message_id": message_id}


def send_needs_revision_reinvestigate(
    task_id: str,
    title: str,
    feedback: str = "",
    chat_id: str | None = None,
) -> dict[str, Any]:
    """Send a Telegram message when solution verification fails.

    Buttons: [Re-investigate] [View Report]
    Re-investigate moves task to investigating and scheduler will re-run with feedback.
    Suppressed in quiet mode (only deploy and critical are sent).
    """
    task_id = (task_id or "").strip()
    title = (title or "(no title)")[:200]
    target_chat = (chat_id or "").strip() or _get_default_chat_id()

    if not task_id:
        return {"sent": False, "chat_id": "", "task_id": "", "message_id": None}
    if not target_chat:
        return {"sent": False, "chat_id": "", "task_id": task_id, "message_id": None}

    try:
        from app.services.agent_telegram_policy import is_quiet_mode
        if is_quiet_mode():
            logger.info("send_needs_revision_reinvestigate: suppressed (quiet mode) task_id=%s", task_id[:12] if task_id else "?")
            return {"sent": False, "chat_id": target_chat, "task_id": task_id, "message_id": None}
    except Exception:
        pass

    feedback_preview = (feedback or "Output does not address task requirements.")[:400]
    lines = [
        "<b>⚠️ Solution verification failed</b>",
        "",
        f"<b>Task:</b> {title}",
        "",
        "<b>Why it blocks progress:</b> The patch output does not address the task requirements.",
        "",
        f"<b>Feedback:</b>\n<pre>{feedback_preview}</pre>",
        "",
        "<b>Next step:</b> Use <b>Re-investigate</b> to iterate with this feedback.",
    ]
    text = "\n".join(lines)
    if len(text) > TELEGRAM_TEXT_LIMIT:
        text = text[: TELEGRAM_TEXT_LIMIT - 3] + "..."

    reply_markup = {
        "inline_keyboard": [
            [
                {"text": "🔁 Re-investigate", "callback_data": f"{PREFIX_REINVESTIGATE}{task_id}"},
                {"text": "📋 View Report", "callback_data": f"{PREFIX_VIEW_REPORT}{task_id}"},
            ],
        ]
    }

    sent, message_id = _send_telegram_message(target_chat, text, reply_markup, message_type="PATCH")
    logger.info(
        "send_needs_revision_reinvestigate task_id=%s sent=%s message_id=%s",
        task_id, sent, message_id,
    )
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
        from app.services._paths import get_writable_dir_for_subdir
        search_dirs = [
            get_writable_dir_for_subdir("docs/agents/bug-investigations"),
            get_writable_dir_for_subdir("docs/agents/telegram-alerts"),
            get_writable_dir_for_subdir("docs/agents/execution-state"),
            get_writable_dir_for_subdir("docs/agents/generated-notes"),
            get_writable_dir_for_subdir("docs/runbooks/triage"),
        ]
        for d in search_dirs:
            for pattern in (f"*-{task_id}.sections.json", f"*{task_id}*.sections.json"):
                for f in d.glob(pattern):
                    data = json.loads(f.read_text(encoding="utf-8"))
                    disk_sections = data.get("sections") or {}
                    if disk_sections:
                        with _STORE_LOCK:
                            _SECTIONS_CACHE[task_id] = disk_sections
                        result = format_openclaw_summary_for_telegram(disk_sections)
                        if "(no structured report available)" not in result:
                            return result
                        # sections exist but empty — try _preamble (already in format)
                        # or fall through to raw .md

        # Fallback: load raw .md when sections.json missing or empty
        for d in search_dirs:
            for prefix in ("notion-bug", "notion-task", "notion-telegram", "notion-execution", "notion-triage"):
                md_path = d / f"{prefix}-{task_id}.md"
                if md_path.exists():
                    try:
                        raw = md_path.read_text(encoding="utf-8")
                        # Skip metadata header (before ---)
                        if "---" in raw:
                            body = raw.split("---", 2)[-1].strip()
                        else:
                            body = raw.strip()
                        if body and len(body) > 30:
                            return f"<b>Investigation:</b>\n{body[:1200]}{'…' if len(body) > 1200 else ''}"
                    except Exception as e:
                        logger.debug("get_openclaw_report_for_task: md read failed %s: %s", md_path, e)
    except Exception as e:
        logger.debug("get_openclaw_report_for_task: sidecar lookup failed task_id=%s: %s", task_id, e)

    doc_path = f"docs/agents/bug-investigations/notion-bug-{task_id}.md"
    return (
        f"<i>No OpenClaw report cached for task {task_id}.</i>\n"
        f"Check: Notion task notes or <code>{doc_path}</code> in the repo."
    )
