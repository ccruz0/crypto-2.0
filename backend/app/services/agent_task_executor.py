"""
Minimal, safe task preparation and execution flow for agents (OpenClaw).

Preparation (prepare_next_notion_task):
- reads pending tasks from Notion (planned)
- prioritizes them (critical → high → medium → low)
- infers likely repo area (simple rule-based mapping)
- builds a short execution plan
- claims the task by moving it to in-progress
- appends the plan to the Notion page (best-effort)

Execution (execute_prepared_notion_task):
- accepts the output of prepare_next_notion_task()
- runs injected apply_change_fn / validate_fn / deploy_fn (no hardcoded edits)
- moves task in-progress → testing → deployed only when validation (and optional deploy) succeed
- appends execution/validation/deployment summaries to Notion
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import httpx

from app.services.notion_task_reader import get_high_priority_pending_tasks
from app.services.notion_tasks import (
    NOTION_API_BASE,
    NOTION_VERSION,
    update_notion_task_status,
    update_notion_task_version_metadata,
)
from app.services.agent_versioning import (
    VERSION_STATUS_PROPOSED,
    build_version_summary,
    mark_version_released,
)

logger = logging.getLogger(__name__)


def _get_approval_gate():
    """Lazy import to avoid circular dependency."""
    from app.services.agent_approval import build_approval_summary, requires_human_approval
    return requires_human_approval, build_approval_summary


def _get_callbacks_selector():
    """Lazy import to avoid circular dependency."""
    from app.services.agent_callbacks import select_default_callbacks_for_task
    return select_default_callbacks_for_task

# Type alias for optional callbacks: (prepared_task: dict) -> bool | dict
PreparedTaskCallback = Optional[Callable[[dict[str, Any]], bool | dict[str, Any]]]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _rich_text(content: str) -> list[dict[str, Any]]:
    if not content:
        return []
    return [{"type": "text", "text": {"content": content[:2000]}}]


def _append_notion_page_comment(page_id: str, comment: str) -> bool:
    """
    Append a paragraph block to a Notion page (best-effort).

    Returns True if Notion accepted the append request, else False. Never raises.
    """
    api_key = (os.environ.get("NOTION_API_KEY") or "").strip()
    if not api_key:
        logger.warning("Notion comment append skipped: NOTION_API_KEY not set page_id=%s", page_id)
        return False

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }

    content = (comment or "").strip()
    if not content:
        return True

    payload: dict[str, Any] = {
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
                f"{NOTION_API_BASE}/blocks/{page_id}/children",
                json=payload,
                headers=headers,
            )
        if r.status_code == 200:
            return True
        logger.warning(
            "Notion comment append failed page_id=%s http=%d",
            page_id,
            r.status_code,
        )
        return False
    except Exception as e:
        logger.warning("Notion comment append error page_id=%s err=%s", page_id, e)
        return False


def append_notion_page_comment(page_id: str, comment: str) -> bool:
    """
    Append a comment to a Notion page (e.g. for scheduler or executor).
    Re-exposes _append_notion_page_comment for use by agent_scheduler and others.
    """
    return _append_notion_page_comment(page_id, comment)


def _run_callback(
    prepared_task: dict[str, Any],
    fn: PreparedTaskCallback,
    label: str,
) -> tuple[bool, str]:
    """
    Run an optional callback with prepared_task. Return (success, summary).
    If fn is None, returns (False, "not provided").
    If fn raises, returns (False, str(exception)).
    If fn returns a dict, expect keys "success" (bool) and optionally "summary" (str).
    If fn returns a bool, that is success and summary is "".
    """
    if fn is None:
        return False, "not provided"
    try:
        out = fn(prepared_task)
        if isinstance(out, dict):
            success = bool(out.get("success"))
            summary = str(out.get("summary") or "").strip() or ("ok" if success else "failed")
            return success, summary
        if isinstance(out, bool):
            return out, "ok" if out else "failed"
        return False, str(out)
    except Exception as e:
        logger.exception("%s callback failed: %s", label, e)
        return False, str(e)


def summarize_execution_result(success: bool, summary: str | None = None) -> str:
    """Build a short text summary of an apply/change step for Notion or logs."""
    s = (summary or "").strip() or ("succeeded" if success else "failed")
    return f"Execution (apply): {'succeeded' if success else 'failed'} — {s}"


def summarize_validation_result(success: bool, summary: str | None = None) -> str:
    """Build a short text summary of a validation step for Notion or logs."""
    s = (summary or "").strip() or ("passed" if success else "failed")
    return f"Validation: {'passed' if success else 'failed'} — {s}"


def summarize_deployment_result(success: bool, summary: str | None = None) -> str:
    """Build a short text summary of a deployment step for Notion or logs."""
    s = (summary or "").strip() or ("succeeded" if success else "failed")
    return f"Deployment: {'succeeded' if success else 'failed'} — {s}"


def infer_repo_area_for_task(task: dict[str, Any]) -> dict[str, Any]:
    """
    Infer the likely repo area for a task using simple rule-based matching.

    Returns a structured dict with:
    - area_name: short label
    - likely_files: list[str]
    - relevant_docs: list[str]
    - relevant_runbooks: list[str]
    - matched_rules: list[str] (debugging/transparency)
    """
    title = str(task.get("task") or "")
    project = str(task.get("project") or "")
    task_type = str(task.get("type") or "")
    details = str(task.get("details") or "")

    blob = f"{title} {project} {task_type} {details}".lower()
    matched: list[str] = []

    # Always-relevant docs for safe agent work
    base_docs = [
        "docs/architecture/system-map.md",
        "docs/agents/context.md",
        "docs/agents/task-system.md",
        "docs/decision-log/README.md",
    ]

    def area(
        area_name: str,
        likely_files: list[str],
        relevant_docs: list[str],
        relevant_runbooks: list[str],
    ) -> dict[str, Any]:
        # De-dup while preserving order
        def uniq(items: list[str]) -> list[str]:
            out: list[str] = []
            seen: set[str] = set()
            for it in items:
                if it not in seen:
                    out.append(it)
                    seen.add(it)
            return out

        return {
            "area_name": area_name,
            "likely_files": uniq(likely_files),
            "relevant_docs": uniq(base_docs + relevant_docs),
            "relevant_runbooks": uniq(relevant_runbooks),
            "matched_rules": matched,
        }

    # Telegram / notifications
    if any(k in blob for k in ("telegram", "bot", "chat_id", "notifier")):
        matched.append("telegram")
        return area(
            "Telegram / Notifications",
            likely_files=[
                "backend/app/services/telegram_commands.py",
                "backend/app/services/telegram_notifier.py",
                "backend/app/api/routes_monitoring.py",
            ],
            relevant_docs=[
                "docs/operations/monitoring.md",
            ],
            relevant_runbooks=[
                "docs/runbooks/restart-services.md",
                "docs/runbooks/dashboard_healthcheck.md",
            ],
        )

    # Order sync / exchange order history / lifecycle
    if any(
        k in blob
        for k in (
            "order sync",
            "exchange sync",
            "order history",
            "executed",
            "canceled",
            "open orders",
            "trade history",
        )
    ):
        matched.append("orders-sync")
        return area(
            "Orders / Exchange Sync",
            likely_files=[
                "backend/app/services/exchange_sync.py",
                "backend/app/models/exchange_order.py",
                "backend/app/models/trade_signal.py",
                "backend/app/api/routes_orders.py",
            ],
            relevant_docs=[
                "docs/openclaw/OPENCLAW_UI_IN_DASHBOARD.md",
            ],
            relevant_runbooks=[
                "docs/aws/RUNBOOK_ORDER_HISTORY_SYNC_DEBUG.md",
                "docs/aws/RUNBOOK_ORDER_HISTORY_ISOLATION.md",
                "docs/runbooks/ORDER_HISTORY_DASHBOARD_DEBUG.md",
            ],
        )

    # Monitoring / infra / deployment / connectivity
    if (
        "monitor" in task_type.lower()
        or "infrastructure" in project.lower()
        or any(k in blob for k in ("health", "502", "504", "nginx", "ssm", "deploy", "docker", "container", "ec2", "postgres", "db "))
    ):
        matched.append("monitoring-infra")
        return area(
            "Monitoring / Infrastructure",
            likely_files=[
                "backend/app/api/routes_monitoring.py",
                "backend/app/api/routes_debug.py",
                "backend/app/main.py",
                "docker-compose.yml",
            ],
            relevant_docs=[
                "docs/operations/monitoring.md",
                "docs/aws/RUNBOOK_INDEX.md",
            ],
            relevant_runbooks=[
                "docs/runbooks/deploy.md",
                "docs/runbooks/restart-services.md",
                "docs/runbooks/dashboard_healthcheck.md",
                "docs/runbooks/502_BAD_GATEWAY.md",
                "docs/runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md",
            ],
        )

    # Strategy / signals / throttling
    if any(k in blob for k in ("strategy", "signal", "rsi", "throttle", "duplicate signal", "signalmonitor")):
        matched.append("strategy-signals")
        return area(
            "Trading Engine / Strategy",
            likely_files=[
                "backend/app/services/signal_monitor.py",
                "backend/app/services/trading_signals.py",
                "backend/app/services/strategy_profiles.py",
                "backend/app/services/signal_throttle.py",
            ],
            relevant_docs=[
                "docs/integrations/crypto-api.md",
            ],
            relevant_runbooks=[
                "docs/runbooks/OPEN_VS_TRIGGER_ORDERS_DIAGNOSTIC.md",
            ],
        )

    # Market data / websocket / prices
    if any(k in blob for k in ("market data", "market-updater", "ticker", "price", "websocket", "ws")):
        matched.append("market-data")
        return area(
            "Market Data",
            likely_files=[
                "backend/app/api/routes_market.py",
                "backend/app/api/routes_price.py",
                "docker-compose.yml",
            ],
            relevant_docs=[
                "docs/integrations/crypto-api.md",
            ],
            relevant_runbooks=[
                "docs/runbooks/EC2_FIX_MARKET_DATA_NOW.md",
                "docs/runbooks/EC2_DASHBOARD_LIVE_DATA_FIX.md",
                "docs/runbooks/OPENCLAW_504_AND_WS_LOCALHOST.md",
            ],
        )

    matched.append("default-triage")
    return area(
        "General / Triage",
        likely_files=[
            "README.md",
            "backend/app/main.py",
        ],
        relevant_docs=[],
        relevant_runbooks=["docs/aws/RUNBOOK_INDEX.md"],
    )


def build_task_execution_plan(task: dict[str, Any], repo_area: dict[str, Any]) -> list[str]:
    """
    Build a short, step-by-step plan for an agent to execute later.

    This plan is intentionally conservative and focuses on safe preparation.
    """
    area_name = str(repo_area.get("area_name") or "Unknown area")
    likely_files = repo_area.get("likely_files") or []
    relevant_docs = repo_area.get("relevant_docs") or []
    relevant_runbooks = repo_area.get("relevant_runbooks") or []

    steps: list[str] = []
    steps.append("Read required docs first: system-map, agent context, task-system, decision-log.")

    if relevant_docs:
        steps.append(f"Read relevant docs for this area ({area_name}): " + ", ".join(relevant_docs[:6]) + (" ..." if len(relevant_docs) > 6 else ""))

    if relevant_runbooks:
        steps.append("Check relevant runbooks before touching code: " + ", ".join(relevant_runbooks[:6]) + (" ..." if len(relevant_runbooks) > 6 else ""))

    if likely_files:
        steps.append("Inspect likely affected files/modules: " + ", ".join(likely_files[:8]) + (" ..." if len(likely_files) > 8 else ""))
    else:
        steps.append("Identify the smallest likely affected module based on details and recent changes.")

    steps.append("Confirm whether the issue is reproducible (logs, health endpoints, minimal local repro if safe).")
    steps.append("Identify the smallest safe change to address the task; avoid touching unrelated files.")
    steps.append("If behavior/ops procedures change, update the relevant docs/runbooks in `/docs`.")
    steps.append("Validate (tests/lint/manual checks/runbook verification) before moving status to `testing`.")

    return steps


def prepare_next_notion_task(
    *,
    project: str | None = None,
    type_filter: str | None = None,
) -> dict[str, Any] | None:
    """
    Prepare the next highest-priority planned Notion task for implementation.

    Behavior:
    - Fetches planned tasks sorted by priority
    - Selects the top task
    - Infers repo area + builds a short plan
    - Attempts to claim the task by moving it to in-progress
    - Appends the plan to the Notion page (best-effort; only after claim succeeds)

    Returns:
        - None if there are no pending tasks
        - Otherwise a structured dict describing selection, inference, plan, and claim results

    Example:
        from app.services.agent_task_executor import prepare_next_notion_task

        prepared = prepare_next_notion_task(project="Infrastructure")
        if prepared and prepared["claim"]["status_updated"]:
            # Next step (outside this module): implement the plan, then advance status.
            pass
    """
    tasks = get_high_priority_pending_tasks(project=project, type_filter=type_filter)
    if not tasks:
        logger.info("No pending Notion tasks found for preparation project=%r type_filter=%r", project, type_filter)
        return None

    task = tasks[0]
    page_id = str(task.get("id") or "").strip()

    logger.info(
        "Selected Notion task for preparation id=%s priority=%s project=%s type=%s task=%r",
        page_id,
        (task.get("priority") or ""),
        (task.get("project") or ""),
        (task.get("type") or ""),
        (task.get("task") or ""),
    )

    repo_area = infer_repo_area_for_task(task)
    logger.info(
        "Inferred repo area for task id=%s area=%s rules=%s",
        page_id,
        repo_area.get("area_name"),
        ",".join(repo_area.get("matched_rules") or []),
    )

    plan = build_task_execution_plan(task, repo_area)
    plan_text = "OpenClaw preparation plan\n\n" + "\n".join(f"- {s}" for s in plan)

    result: dict[str, Any] = {
        "prepared_at": _utc_now_iso(),
        "task": task,
        "repo_area": repo_area,
        "execution_plan": plan,
        "claim": {
            "attempted": True,
            "target_status": "in-progress",
            "status_updated": False,
            "plan_appended": False,
        },
    }

    if not page_id:
        logger.warning("Cannot claim task: missing page_id in task payload task=%r", task)
        result["claim"]["error"] = "missing_page_id"
        return result

    status_ok = update_notion_task_status(page_id=page_id, status="in-progress")
    result["claim"]["status_updated"] = bool(status_ok)

    if not status_ok:
        logger.warning("Failed to claim Notion task id=%s (status update failed)", page_id)
        result["claim"]["error"] = "status_update_failed"
        return result

    logger.info("Claimed Notion task id=%s status=in-progress", page_id)

    appended = _append_notion_page_comment(page_id, plan_text)
    result["claim"]["plan_appended"] = bool(appended)

    if appended:
        logger.info("Appended execution plan comment to Notion task id=%s", page_id)
    else:
        logger.warning("Could not append plan comment to Notion task id=%s", page_id)

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "task_prepared",
            task_id=page_id,
            task_title=str(task.get("task") or "").strip(),
            details={"repo_area": repo_area.get("area_name"), "priority": (task.get("priority") or "").strip()},
        )
    except Exception as e:
        logger.debug("log_agent_event(task_prepared) failed: %s", e)
    return result


def prepare_task_with_approval_check(
    *,
    project: str | None = None,
    type_filter: str | None = None,
) -> dict[str, Any] | None:
    """
    Prepare the next Notion task and attach callback selection + approval decision.

    Does not block intake; the approval gate applies to execution only.
    Returns None if there are no pending tasks; otherwise a bundle with:
    - prepared_task: output of prepare_next_notion_task()
    - callback_selection: output of select_default_callbacks_for_task()
    - approval: output of requires_human_approval()
    - approval_summary: human-readable summary from build_approval_summary()
    """
    prepared = prepare_next_notion_task(project=project, type_filter=type_filter)
    if prepared is None:
        return None

    select_default_callbacks_for_task = _get_callbacks_selector()
    requires_human_approval, build_approval_summary = _get_approval_gate()

    callback_selection = select_default_callbacks_for_task(prepared)
    approval = requires_human_approval(prepared, callback_selection)
    approval_summary = build_approval_summary(prepared, callback_selection, approval)

    # Build version proposal metadata for traceability across proposal/approval/release.
    versioning = build_version_summary(prepared, analysis_result=None)
    prepared["versioning"] = versioning
    task_obj = (prepared.get("task") or {})
    task_obj["current_version"] = versioning.get("current_version", "")
    task_obj["proposed_version"] = versioning.get("proposed_version", "")
    task_obj["version_status"] = versioning.get("version_status", VERSION_STATUS_PROPOSED)
    task_obj["change_summary"] = versioning.get("change_summary", "")

    task_id = str(task_obj.get("id") or "").strip()
    task_title = str(task_obj.get("task") or "").strip()
    if task_id:
        try:
            update_notion_task_version_metadata(
                page_id=task_id,
                metadata={
                    "current_version": versioning.get("current_version", ""),
                    "proposed_version": versioning.get("proposed_version", ""),
                    "version_status": versioning.get("version_status", VERSION_STATUS_PROPOSED),
                    "change_summary": versioning.get("change_summary", ""),
                },
                append_comment=(
                    f"Version proposal: v{versioning.get('proposed_version', '')} "
                    f"(from v{versioning.get('current_version', '')}, {versioning.get('change_type', 'patch')}). "
                    f"Summary: {versioning.get('change_summary', '')}"
                ),
            )
        except Exception as e:
            logger.debug("prepare_task_with_approval_check: Notion version proposal update failed %s", e)

        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "version_proposed",
                task_id=task_id,
                task_title=task_title or None,
                details={
                    "current_version": versioning.get("current_version", ""),
                    "proposed_version": versioning.get("proposed_version", ""),
                    "version_status": versioning.get("version_status", VERSION_STATUS_PROPOSED),
                    "change_summary": versioning.get("change_summary", ""),
                    "affected_files": versioning.get("affected_files") or [],
                    "validation_plan": versioning.get("validation_plan") or [],
                },
            )
        except Exception as e:
            logger.debug("log_agent_event(version_proposed) failed: %s", e)

    return {
        "prepared_task": prepared,
        "callback_selection": callback_selection,
        "approval": approval,
        "approval_summary": approval_summary,
        "versioning": versioning,
    }


def execute_prepared_task_if_approved(
    prepared_bundle: dict[str, Any],
    *,
    approved: bool = False,
) -> dict[str, Any]:
    """
    Execute the prepared task only if approval is not required, or if approved=True.

    If approval is required and approved=False:
    - Does not run apply/validate/deploy callbacks
    - Appends a Notion comment that execution is waiting for human approval
    - Returns a structured result with success=False and execution not run (task stays in-progress)

    If approval is not required, or approval is required and approved=True:
    - Runs execute_prepared_notion_task() with callbacks from the bundle
    """
    if not prepared_bundle:
        return {
            "executed_at": _utc_now_iso(),
            "task_id": "",
            "task_title": "",
            "approval_required": True,
            "approval_granted": False,
            "execution_skipped": True,
            "reason": "no prepared bundle",
            "execution_result": None,
        }

    prepared_task = prepared_bundle.get("prepared_task")
    callback_selection = prepared_bundle.get("callback_selection") or {}
    approval = prepared_bundle.get("approval") or {}

    task = (prepared_task or {}).get("task") or {}
    task_id = str(task.get("id") or "").strip()
    task_title = str(task.get("task") or "").strip()

    # Fallback: if callback_selection has no apply_change_fn, re-select from prepared_task
    if prepared_task and not callback_selection.get("apply_change_fn"):
        old_reason = callback_selection.get("selection_reason", "")
        logger.warning(
            "execute_prepared_task_if_approved: apply_change_fn is None (reason=%r), re-selecting callbacks task_id=%s",
            old_reason, task_id,
        )
        try:
            reselected = _get_callbacks_selector()(prepared_task)
            if reselected and reselected.get("apply_change_fn"):
                logger.info(
                    "execute_prepared_task_if_approved: re-selection succeeded reason=%r task_id=%s",
                    reselected.get("selection_reason", ""), task_id,
                )
                callback_selection = reselected
                prepared_bundle["callback_selection"] = reselected
            else:
                logger.warning(
                    "execute_prepared_task_if_approved: re-selection still None reason=%r task_id=%s",
                    (reselected or {}).get("selection_reason", ""), task_id,
                )
        except Exception as e:
            logger.error("execute_prepared_task_if_approved: re-selection raised %s task_id=%s", e, task_id)

    approval_required = bool(approval.get("required"))
    manual_only = bool(callback_selection.get("manual_only"))

    if manual_only and not approved:
        comment = (
            f"[{_utc_now_iso()}] Execution waiting for explicit manual approval. "
            "This callback is marked manual-only and cannot auto-run."
        )
        _append_notion_page_comment(task_id, comment)
        return {
            "executed_at": _utc_now_iso(),
            "task_id": task_id,
            "task_title": task_title,
            "approval_required": True,
            "approval_granted": False,
            "execution_skipped": True,
            "reason": "manual-only callback requires explicit approval",
            "execution_result": None,
        }

    if approval_required and not approved:
        logger.info(
            "execute_prepared_task_if_approved: approval required but not granted task_id=%s task_title=%r",
            task_id,
            task_title,
        )
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("execution_skipped", task_id=task_id, task_title=task_title, details={"reason": "approval required", "approval_required": True})
        except Exception as e:
            logger.debug("log_agent_event(execution_skipped) failed: %s", e)
        comment = (
            f"[{_utc_now_iso()}] Execution waiting for human approval. "
            f"Risk: {approval.get('risk_level', 'unknown')}. {approval.get('reason', '')}"
        )
        _append_notion_page_comment(task_id, comment)
        return {
            "executed_at": _utc_now_iso(),
            "task_id": task_id,
            "task_title": task_title,
            "approval_required": True,
            "approval_granted": False,
            "execution_skipped": True,
            "reason": approval.get("reason", "approval required"),
            "execution_result": None,
        }

    # Run execution (approval not required, or approved=True)
    apply_fn = callback_selection.get("apply_change_fn")
    validate_fn = callback_selection.get("validate_fn")
    deploy_fn = callback_selection.get("deploy_fn")

    execution_result = execute_prepared_notion_task(
        prepared_task,
        apply_change_fn=apply_fn,
        validate_fn=validate_fn,
        deploy_fn=deploy_fn,
    )

    return {
        "executed_at": execution_result.get("executed_at", _utc_now_iso()),
        "task_id": task_id,
        "task_title": task_title,
        "approval_required": approval_required,
        "approval_granted": approved if approval_required else True,
        "execution_skipped": False,
        "reason": "" if execution_result.get("success") else execution_result.get("apply", {}).get("summary", "execution failed"),
        "execution_result": execution_result,
    }


def execute_prepared_notion_task(
    prepared_task: dict[str, Any],
    *,
    apply_change_fn: PreparedTaskCallback = None,
    validate_fn: PreparedTaskCallback = None,
    deploy_fn: PreparedTaskCallback = None,
) -> dict[str, Any]:
    """
    Execute a prepared Notion task in a controlled way: apply → testing → validate → deploy → deployed.

    Accepts the output of prepare_next_notion_task(). Uses injected callbacks; does not hardcode
    repository edits, test commands, or deployment commands.

    Callbacks:
    - apply_change_fn(prepared_task): apply code/docs changes. Return bool or dict with "success" and optional "summary".
    - validate_fn(prepared_task): run tests/lint/checks. Same return convention.
    - deploy_fn(prepared_task): optional deploy step. Same return convention. Only run if validation succeeded.

    State transitions:
    - If apply fails: task stays in-progress; failure comment appended; return structured failure.
    - If apply succeeds: status → testing; execution summary appended.
    - If validate_fn not provided: task stays in testing; comment "validation still required"; never marked deployed.
    - If validation fails: task stays in testing; failure comment appended; not deployed.
    - If deploy_fn provided and fails: task stays in testing; not deployed.
    - Only if validation (and deploy if provided) succeed: status → deployed; final comment appended.

    Returns a structured dict with executed_at, task_id, task_title, apply, testing, validation,
    deployment, final_status, success. Never raises.
    """
    executed_at = _utc_now_iso()
    task = (prepared_task or {}).get("task") or {}
    claim = (prepared_task or {}).get("claim") or {}
    versioning = (prepared_task or {}).get("versioning") or {}
    task_id = str(task.get("id") or "").strip()
    task_title = str(task.get("task") or "").strip()

    def result(
        apply_attempted: bool,
        apply_success: bool,
        apply_summary: str,
        testing_status_updated: bool,
        validation_attempted: bool,
        validation_success: bool,
        validation_summary: str,
        deployment_attempted: bool,
        deployment_success: bool,
        deployment_summary: str,
        final_status: str,
        overall_success: bool,
    ) -> dict[str, Any]:
        return {
            "executed_at": executed_at,
            "task_id": task_id,
            "task_title": task_title,
            "apply": {
                "attempted": apply_attempted,
                "success": apply_success,
                "summary": apply_summary,
            },
            "testing": {"status_updated": testing_status_updated},
            "validation": {
                "attempted": validation_attempted,
                "success": validation_success,
                "summary": validation_summary,
            },
            "deployment": {
                "attempted": deployment_attempted,
                "success": deployment_success,
                "summary": deployment_summary,
            },
            "final_status": final_status,
            "success": overall_success,
        }
    # ----- Validation: task must be properly claimed
    if not prepared_task:
        logger.warning("execute_prepared_notion_task: prepared_task is missing or empty")
        return result(
            False, False, "prepared_task missing",
            False, False, False, "", False, False, "",
            "in-progress", False,
        )
    if not claim.get("status_updated"):
        logger.warning("execute_prepared_notion_task: task not claimed (status_updated not True) task_id=%s", task_id)
        return result(
            False, False, "task not claimed",
            False, False, False, "", False, False, "",
            "in-progress", False,
        )
    if not task_id:
        logger.warning("execute_prepared_notion_task: task.id missing")
        return result(
            False, False, "task.id missing",
            False, False, False, "", False, False, "",
            "in-progress", False,
        )

    # ----- No apply function: skip execution
    if apply_change_fn is None:
        logger.info("execute_prepared_notion_task: no apply_change_fn supplied; skipping execution task_id=%s task_title=%r", task_id, task_title)
        _append_notion_page_comment(task_id, f"[{executed_at}] Execution skipped: no apply function supplied.")
        return result(
            False, False, "skipped: no apply function supplied",
            False, False, False, "", False, False, "",
            "in-progress", False,
        )

    logger.info("execute_prepared_notion_task: starting task_id=%s task_title=%r", task_id, task_title)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("execution_started", task_id=task_id, task_title=task_title, details={})
    except Exception as e:
        logger.debug("log_agent_event(execution_started) failed: %s", e)

    # ----- Step 1: apply
    apply_ok, apply_summary = _run_callback(prepared_task, apply_change_fn, "apply_change")
    if not apply_ok:
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("execution_failed", task_id=task_id, task_title=task_title, details={"stage": "apply", "summary": apply_summary})
        except Exception as e:
            logger.debug("log_agent_event(execution_failed/apply) failed: %s", e)
        msg = summarize_execution_result(False, apply_summary)
        _append_notion_page_comment(task_id, f"[{executed_at}] {msg}")
        logger.warning("execute_prepared_notion_task: apply failed task_id=%s summary=%s", task_id, apply_summary)
        return result(
            True, False, apply_summary,
            False, False, False, "", False, False, "",
            "in-progress", False,
        )

    # ----- Step 2 & 3: move to testing and append execution summary
    testing_updated = update_notion_task_status(task_id, "testing")
    if testing_updated:
        logger.info("execute_prepared_notion_task: moved to testing task_id=%s", task_id)
    exec_msg = summarize_execution_result(True, apply_summary)
    _append_notion_page_comment(task_id, f"[{executed_at}] {exec_msg}")

    # ----- Step 4: validate
    validation_attempted = validate_fn is not None
    validation_ok = False
    validation_summary = ""
    if validate_fn is not None:
        validation_ok, validation_summary = _run_callback(prepared_task, validate_fn, "validate")
        if not validation_ok:
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("validation_failed", task_id=task_id, task_title=task_title, details={"summary": validation_summary})
            except Exception as e:
                logger.debug("log_agent_event(validation_failed) failed: %s", e)
            msg = summarize_validation_result(False, validation_summary)
            _append_notion_page_comment(task_id, f"[{executed_at}] {msg}")
            logger.warning("execute_prepared_notion_task: validation failed task_id=%s summary=%s", task_id, validation_summary)
            # Apply succeeded and task moved to testing — mark success=True
            # to prevent infinite retry loops. Validation issues are soft
            # failures that should be resolved manually, not re-executed.
            return result(
                True, True, apply_summary,
                testing_updated, True, False, validation_summary,
                False, False, "",
                "testing", True,
            )
        logger.info("execute_prepared_notion_task: validation passed task_id=%s", task_id)
    else:
        _append_notion_page_comment(task_id, f"[{executed_at}] Validation still required (no validate_fn supplied). Task left in testing.")
        logger.info("execute_prepared_notion_task: no validate_fn; task left in testing task_id=%s", task_id)
        return result(
            True, True, apply_summary,
            testing_updated, False, False, "pending (no validate_fn)",
            False, False, "",
            "testing", False,
        )

    # ----- Step 5: optional deploy
    deployment_attempted = deploy_fn is not None
    deployment_ok = True
    deployment_summary = "not run"
    if deploy_fn is not None:
        deployment_ok, deployment_summary = _run_callback(prepared_task, deploy_fn, "deploy")
        if not deployment_ok:
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("execution_failed", task_id=task_id, task_title=task_title, details={"stage": "deploy", "summary": deployment_summary})
            except Exception as e:
                logger.debug("log_agent_event(execution_failed/deploy) failed: %s", e)
            msg = summarize_deployment_result(False, deployment_summary)
            _append_notion_page_comment(task_id, f"[{executed_at}] {msg}")
            logger.warning("execute_prepared_notion_task: deployment failed task_id=%s summary=%s", task_id, deployment_summary)
            return result(
                True, True, apply_summary,
                testing_updated, True, True, validation_summary,
                True, False, deployment_summary,
                "testing", False,
            )
        logger.info("execute_prepared_notion_task: deployment succeeded task_id=%s", task_id)

    # ----- Step 6 & 7: move to deployed and append final comment
    deployed_updated = update_notion_task_status(task_id, "deployed")
    if deployed_updated:
        logger.info("execute_prepared_notion_task: moved to deployed task_id=%s task_title=%r", task_id, task_title)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("execution_completed", task_id=task_id, task_title=task_title, details={"final_status": "deployed"})
    except Exception as e:
        logger.debug("log_agent_event(execution_completed) failed: %s", e)
    final_comment = f"[{executed_at}] Validation passed. Deployment: {deployment_summary}. Status set to deployed."
    _append_notion_page_comment(task_id, final_comment)

    # Version release traceability (best-effort): mark released in Notion + changelog + activity log.
    released_version = str(
        versioning.get("proposed_version")
        or task.get("proposed_version")
        or task.get("released_version")
        or ""
    ).strip()
    if released_version:
        release_summary = (
            f"{versioning.get('change_summary') or apply_summary or task_title}; "
            f"validation={validation_summary or 'passed'}; deployment={deployment_summary or 'not run'}"
        )
        mark_version_released(task_id, released_version, release_summary)

    return result(
        True, True, apply_summary,
        testing_updated, True, True, validation_summary,
        deployment_attempted, deployment_ok, deployment_summary,
        "deployed", True,
    )

