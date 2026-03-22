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

from app.services.notion_task_reader import get_high_priority_pending_tasks, get_notion_task_by_id
from app.services.notion_tasks import (
    NOTION_API_BASE,
    NOTION_VERSION,
    update_notion_task_metadata,
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
    dry_run = (os.environ.get("AGENT_DRY_RUN") or os.environ.get("NOTION_DRY_RUN") or "").strip().lower() in ("1", "true", "yes")
    if dry_run:
        logger.info("dry_run skip append_notion_page_comment page_id=%s", page_id[:12] if page_id else "?")
        return True
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
) -> tuple[bool, str, bool]:
    """
    Run an optional callback with prepared_task. Return (success, summary, retryable).
    If fn is None, returns (False, "not provided", False).
    If fn raises, returns (False, str(exception), False).
    If fn returns a dict, expect keys "success" (bool), optionally "summary" (str), "retryable" (bool).
    If fn returns a bool, that is success and summary is "".
    """
    if fn is None:
        return False, "not provided", False
    try:
        out = fn(prepared_task)
        if isinstance(out, dict):
            success = bool(out.get("success"))
            summary = str(out.get("summary") or "").strip() or ("ok" if success else "failed")
            retryable = bool(out.get("retryable", False))
            return success, summary, retryable
        if isinstance(out, bool):
            return out, "ok" if out else "failed", False
        return False, str(out), False
    except Exception as e:
        logger.exception("%s callback failed: %s", label, e)
        return False, str(e), False


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


def _enrich_metadata_from_openclaw(prepared_task: dict[str, Any], task_id: str) -> None:
    """Best-effort: populate Notion task metadata fields from OpenClaw structured sections.

    Reads ``prepared_task["_openclaw_sections"]`` (stashed by the OpenClaw
    callback) and writes matching fields to Notion via
    ``update_notion_task_metadata``.  Silently no-ops when sections are
    absent or the Notion update fails.
    """
    sections = (prepared_task or {}).get("_openclaw_sections") or {}
    if not sections or not task_id:
        return

    metadata: dict[str, str] = {}

    risk_level = sections.get("Risk Level")
    if risk_level and risk_level.strip().lower() != "n/a":
        first_line = risk_level.strip().splitlines()[0]
        metadata["risk_level"] = first_line[:100]

    affected_files = sections.get("Affected Files")
    if affected_files and affected_files.strip().lower() != "n/a":
        metadata["repo"] = affected_files.strip()[:200]

    testing_plan = sections.get("Testing Plan")
    if testing_plan and testing_plan.strip().lower() != "n/a":
        metadata["test_status"] = "plan-available"

    if not metadata:
        return

    try:
        result = update_notion_task_metadata(task_id, metadata)
        logger.info(
            "OpenClaw metadata enrichment task_id=%s updated=%s skipped=%s",
            task_id, result.get("updated_fields"), result.get("skipped_fields"),
        )
    except Exception as e:
        logger.warning("_enrich_metadata_from_openclaw failed task_id=%s: %s", task_id, e)


def _generate_cursor_handoff(prepared_task: dict[str, Any], task_id: str) -> None:
    """Best-effort: generate and save a Cursor implementation handoff prompt.

    Only runs when OpenClaw structured sections are available on the
    prepared_task.  Failures are logged and silently ignored.
    """
    sections = (prepared_task or {}).get("_openclaw_sections") or {}
    if not sections or not task_id:
        return
    try:
        from app.services.cursor_handoff import generate_cursor_handoff
        result = generate_cursor_handoff(prepared_task)
        if result.get("success"):
            logger.info("Cursor handoff generated task_id=%s path=%s", task_id, result.get("path"))
        else:
            logger.debug("Cursor handoff generation returned success=False task_id=%s", task_id)
    except Exception as e:
        logger.warning("_generate_cursor_handoff failed task_id=%s: %s", task_id, e)


def _record_test_gate_result(
    task_id: str,
    validation_attempted: bool,
    validation_success: bool,
    validation_summary: str,
    current_status: str,
) -> None:
    """Best-effort: record the validation outcome via the test gate.

    Writes the ``test_status`` Notion metadata field.  Does NOT advance
    status here — the legacy executor already handles status transitions
    directly.  The ``advance_on_pass=False`` flag ensures this is
    metadata-only so the legacy flow is not disrupted.
    """
    try:
        from app.services.task_test_gate import record_test_result, test_outcome_from_validation
        outcome, summary = test_outcome_from_validation(validation_attempted, validation_success, validation_summary)
        record_test_result(
            task_id,
            outcome,
            summary=summary,
            advance_on_pass=False,
            current_status=current_status,
        )
    except Exception as e:
        logger.debug("_record_test_gate_result failed task_id=%s: %s", task_id, e)


def _run_post_deploy_smoke_check(task_id: str, prepared_task: dict[str, Any]) -> str:
    """Run a post-deploy smoke check when enabled.

    Returns one of:
        ``"passed"``  — smoke check ran and passed; caller should mark task done.
        ``"blocked"`` — smoke check ran and failed; caller should not advance.
        ``""``        — smoke check was not enabled/applicable; legacy flow.
    """
    enable = (os.environ.get("ATP_SMOKE_CHECK_ENABLED") or "").strip().lower()
    if enable not in ("1", "true", "yes"):
        return ""
    try:
        from app.services.deploy_smoke_check import (
            run_smoke_check,
            record_smoke_check_result,
        )
        logger.info("execute_prepared_notion_task: running post-deploy smoke check task_id=%s", task_id)
        smoke = run_smoke_check(task_id=task_id)
        record_smoke_check_result(
            task_id,
            smoke,
            advance_on_pass=False,
            current_status="deploying",
        )
        if smoke.get("ok"):
            logger.info("execute_prepared_notion_task: smoke check passed task_id=%s", task_id)
            return "passed"
        logger.warning(
            "execute_prepared_notion_task: smoke check FAILED task_id=%s summary=%s",
            task_id, smoke.get("summary"),
        )
        return "blocked"
    except Exception as exc:
        logger.warning("_run_post_deploy_smoke_check failed task_id=%s: %s", task_id, exc)
        return ""


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
    exec_mode = (task.get("execution_mode") or "normal").strip().lower()
    if exec_mode not in ("strict", "normal"):
        exec_mode = "normal"
    task_type = (task.get("type") or "").strip().lower()
    task_title = (task.get("task") or "").strip()
    is_patch_eligible = task_type == "patch" or task_title.startswith("PATCH:")
    logger.info(
        "notion_task_detected task_id=%s title=%s type=%s execution_mode=%s",
        page_id[:12] if page_id else "?",
        (task_title[:50] + "…" if len(task_title) > 50 else task_title) or "?",
        task.get("type") or "?",
        exec_mode,
    )
    logger.info(
        "selected_task_for_execution task_id=%s title=%s type=%s status=%s patch_eligible=%s execution_mode=%s",
        page_id[:12] if page_id else "?",
        (task_title[:50] + "…" if len(task_title) > 50 else task_title) or "?",
        task.get("type") or "?",
        task.get("status") or "?",
        is_patch_eligible,
        exec_mode,
    )
    if is_patch_eligible:
        logger.info("patch_task_picked task_id=%s", page_id[:12] if page_id else "?")
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


def prepare_task_by_id(task_id: str) -> dict[str, Any] | None:
    """
    Prepare a specific Notion task by ID (for targeted runs).

    The task must be in a pickable status (planned, backlog, ready-for-investigation, blocked).
    Returns the same structure as prepare_next_notion_task, or None if task not found/not pickable.
    """
    task_id = (task_id or "").strip()
    if not task_id:
        return None
    task = get_notion_task_by_id(task_id)
    if not task:
        logger.warning("prepare_task_by_id: task not found task_id=%s", task_id)
        return None
    status = (task.get("status") or "").strip().lower()
    pickable = status in ("planned", "backlog", "ready-for-investigation", "blocked", "needs-revision", "in-progress")
    if not pickable:
        logger.warning("prepare_task_by_id: task not pickable task_id=%s status=%r", task_id, status)
        return None
    page_id = str(task.get("id") or "").strip()
    exec_mode = task.get("execution_mode", "?")
    logger.info(
        "execution_mode_trace prepare_task_by_id task_id=%s execution_mode=%s",
        page_id[:12] if page_id else "?",
        exec_mode,
    )
    if exec_mode == "strict":
        logger.info("STRICT MODE DETECTED at prepare_task_by_id task_id=%s", page_id[:12] if page_id else "?")
    repo_area = infer_repo_area_for_task(task)
    plan = build_task_execution_plan(task, repo_area)
    plan_text = "OpenClaw preparation plan\n\n" + "\n".join(f"- {s}" for s in plan)
    result: dict[str, Any] = {
        "prepared_at": _utc_now_iso(),
        "task": task,
        "repo_area": repo_area,
        "execution_plan": plan,
        "claim": {"attempted": True, "target_status": "in-progress", "status_updated": False, "plan_appended": False},
    }
    status_ok = update_notion_task_status(page_id=page_id, status="in-progress")
    result["claim"]["status_updated"] = bool(status_ok)
    if not status_ok:
        logger.warning("prepare_task_by_id: failed to claim task_id=%s", page_id)
        result["claim"]["error"] = "status_update_failed"
        return result
    appended = _append_notion_page_comment(page_id, plan_text)
    result["claim"]["plan_appended"] = bool(appended)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("task_prepared", task_id=page_id, task_title=str(task.get("task") or "").strip(), details={"repo_area": repo_area.get("area_name"), "priority": (task.get("priority") or "").strip()})
    except Exception as e:
        logger.debug("log_agent_event(task_prepared) failed: %s", e)
    return result


def prepare_task_with_approval_check(
    *,
    project: str | None = None,
    type_filter: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    """
    Prepare the next Notion task and attach callback selection + approval decision.

    If task_id is provided, prepares that specific task (must be in planned/backlog/ready-for-investigation/blocked).
    Otherwise fetches the next highest-priority pending task.

    Does not block intake; the approval gate applies to execution only.
    Returns None if there are no pending tasks; otherwise a bundle with:
    - prepared_task: output of prepare_next_notion_task()
    - callback_selection: output of select_default_callbacks_for_task()
    - approval: output of requires_human_approval()
    - approval_summary: human-readable summary from build_approval_summary()
    """
    if task_id:
        prepared = prepare_task_by_id(task_id)
    else:
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
    # Propagate execution_mode to top level so executor and callbacks can read it reliably
    if task_obj.get("execution_mode"):
        prepared["execution_mode"] = task_obj["execution_mode"]
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
    #
    # Extended lifecycle: tasks whose callback pack is marked manual_only
    # use the full investigation → patch-approval → deploy-approval flow
    # instead of the legacy in-progress → testing → deployed shortcut.
    _cb_manual_only = bool(callback_selection.get("manual_only"))
    if _cb_manual_only and prepared_task:
        prepared_task["_use_extended_lifecycle"] = True

    _task_type_for_log = str(((prepared_task or {}).get("task") or {}).get("type") or "")
    logger.info(
        "execute_prepared_task_if_approved: LIFECYCLE DECISION task_id=%s "
        "task_type=%r manual_only=%s _use_extended_lifecycle=%s "
        "selection_reason=%r",
        task_id,
        _task_type_for_log,
        _cb_manual_only,
        bool((prepared_task or {}).get("_use_extended_lifecycle")),
        callback_selection.get("selection_reason", ""),
    )

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
    use_extended_lifecycle = bool((prepared_task or {}).get("_use_extended_lifecycle"))
    if use_extended_lifecycle:
        logger.info("investigation_started task_id=%s", task_id[:12] if task_id else "?")
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("execution_started", task_id=task_id, task_title=task_title, details={})
    except Exception as e:
        logger.debug("log_agent_event(execution_started) failed: %s", e)

    # ----- Step 1: apply
    apply_ok, apply_summary, apply_retryable = _run_callback(prepared_task, apply_change_fn, "apply_change")
    if not apply_ok:
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("execution_failed", task_id=task_id, task_title=task_title, details={"stage": "apply", "summary": apply_summary, "retryable": apply_retryable})
        except Exception as e:
            logger.debug("log_agent_event(execution_failed/apply) failed: %s", e)
        msg = summarize_execution_result(False, apply_summary)
        _append_notion_page_comment(task_id, f"[{executed_at}] {msg}")
        logger.warning("execute_prepared_notion_task: apply failed task_id=%s summary=%s retryable=%s", task_id, apply_summary, apply_retryable)
        # Retryable LLM failures: move to ready-for-investigation so scheduler can retry
        if apply_retryable:
            try:
                from app.services.notion_tasks import TASK_STATUS_READY_FOR_INVESTIGATION
                update_notion_task_status(
                    task_id,
                    TASK_STATUS_READY_FOR_INVESTIGATION,
                    append_comment=f"[{executed_at}] LLM temporary failure (rate limit/timeout). Moved to ready-for-investigation for retry.",
                )
                return result(
                    True, False, apply_summary,
                    False, False, False, "", False, False, "",
                    "ready-for-investigation", False,
                )
            except Exception as e:
                logger.warning("execute_prepared_notion_task: move to ready-for-investigation failed: %s", e)
        return result(
            True, False, apply_summary,
            False, False, False, "", False, False, "",
            "in-progress", False,
        )

    # ----- Step 1b: enrich Notion metadata from OpenClaw structured sections
    _enrich_metadata_from_openclaw(prepared_task, task_id)

    # ----- Step 1c: generate Cursor handoff prompt (best-effort, never blocks)
    _generate_cursor_handoff(prepared_task, task_id)

    # ----- Extended lifecycle gate: investigation-complete -----
    # For manual_only tasks the executor pauses here and sends a Telegram
    # message with [Approve Patch] / [Reject] / [View Report].  The human
    # decision resumes the lifecycle via the existing callback handlers
    # (patch_approve → ready-for-patch, task_reject → rejected).
    use_extended_lifecycle = bool((prepared_task or {}).get("_use_extended_lifecycle"))
    logger.info(
        "execute_prepared_notion_task: LIFECYCLE BRANCH task_id=%s "
        "_use_extended_lifecycle=%s (extended=%s, legacy=%s)",
        task_id,
        use_extended_lifecycle,
        "YES" if use_extended_lifecycle else "no",
        "no" if use_extended_lifecycle else "YES",
    )
    if use_extended_lifecycle:
        logger.info("investigation_completed task_id=%s", task_id[:12] if task_id else "?")
        # Validate artifact AND sidecar exist before advancing. Check all known artifact paths.
        try:
            from app.services.agent_recovery import artifact_and_sidecar_exist_for_task
            _artifact_ok, _artifact_reason = artifact_and_sidecar_exist_for_task(task_id, min_size=200)
        except Exception as e:
            logger.warning(
                "execute_prepared_notion_task: artifact check failed task_id=%s: %s",
                task_id, e,
            )
            _artifact_ok, _artifact_reason = False, str(e)
        if not _artifact_ok:
            logger.warning(
                "ready_for_patch_blocked_missing_artifact task_id=%s reason=%s",
                task_id[:12] if task_id else "?", _artifact_reason,
            )
            logger.info(
                "validation_before_ready_for_patch task_id=%s passed=False reason=%s",
                task_id[:12] if task_id else "?", _artifact_reason,
            )
            _append_notion_page_comment(
                task_id,
                f"[{executed_at}] Investigation artifact missing or incomplete ({_artifact_reason}) — staying in-progress. Retry next cycle.",
            )
            return result(
                True, True, apply_summary,
                False, False, False, "",
                False, False, "",
                "in-progress", False,
            )
        logger.info(
            "validation_before_ready_for_patch task_id=%s passed=True",
            task_id[:12] if task_id else "?",
        )
        # Strict mode: validate proof before advancing — block ready-for-patch if criteria not met
        _exec_mode = (
            (prepared_task or {}).get("execution_mode")
            or ((prepared_task or {}).get("task") or {}).get("execution_mode")
            or "normal"
        )
        logger.info(
            "execution_mode_trace before_auto_advance task_id=%s execution_mode=%s prepared_task_keys=%s task_keys=%s",
            task_id,
            _exec_mode,
            list((prepared_task or {}).keys()),
            list(((prepared_task or {}).get("task") or {}).keys()),
        )
        if _exec_mode == "strict":
            logger.info("STRICT MODE ACTIVE at auto-advance gate task_id=%s — will validate proof", task_id)
        if isinstance(_exec_mode, str) and _exec_mode.strip().lower() == "strict":
            try:
                from app.services.agent_recovery import get_artifact_content_for_task
                from app.services.openclaw_client import validate_strict_mode_proof
                artifact_body = get_artifact_content_for_task(task_id)
                proof_ok, proof_reason = validate_strict_mode_proof(artifact_body)
                if not proof_ok:
                    logger.warning(
                        "strict_proof_failed task_id=%s reason=%s",
                        task_id[:12] if task_id else "?",
                        proof_reason[:200] if proof_reason else "?",
                    )
                    _append_notion_page_comment(
                        task_id,
                        f"[{executed_at}] Strict mode: proof criteria not met — staying in-progress. {proof_reason}",
                    )
                    return result(
                        True, True, apply_summary,
                        False, False, False, "",
                        False, False, "",
                        "in-progress", False,
                    )
                # Strict proof passed — create Cursor-ready patch task (handoff). Invariant: PATCH MUST exist.
                logger.info("strict_proof_passed task_id=%s", task_id[:12] if task_id else "?")
                patch_task = None
                handoff_err = None
                for attempt in (1, 2):  # fallback retry once
                    try:
                        from app.services.notion_tasks import create_patch_task_from_investigation
                        patch_task = create_patch_task_from_investigation(
                            investigation_task_id=task_id,
                            investigation_title=task_title,
                            artifact_body=artifact_body or "",
                            sections=(prepared_task or {}).get("_openclaw_sections") or {},
                            task=task,
                            repo_area=(prepared_task or {}).get("repo_area") or {},
                        )
                        if patch_task:
                            break
                    except Exception as e:
                        handoff_err = e
                        if attempt == 1:
                            logger.warning(
                                "execute_prepared_notion_task: create_patch_task_from_investigation attempt=1 failed task_id=%s: %s — retrying",
                                task_id, e,
                            )
                        else:
                            logger.warning(
                                "execute_prepared_notion_task: create_patch_task_from_investigation attempt=2 failed task_id=%s: %s",
                                task_id, e,
                            )
                if patch_task:
                    logger.info(
                        "patch_task_created task_id=%s patch_id=%s",
                        task_id[:12] if task_id else "?",
                        (patch_task.get("id") or "")[:12] or "?",
                    )
                    logger.info("strict_patch_invariant_enforced task_id=%s", task_id[:12] if task_id else "?")
                else:
                    # Invariant: strict + proof passed => PATCH must exist. Block advance and alert.
                    err_msg = str(handoff_err or "create_patch_task_from_investigation returned None")[:300]
                    logger.warning(
                        "strict_patch_creation_failed task_id=%s reason=%s",
                        task_id[:12] if task_id else "?",
                        err_msg,
                    )
                    logger.info("strict_patch_invariant_enforced task_id=%s block_advance=patch_creation_failed", task_id[:12] if task_id else "?")
                    try:
                        from app.services.notion_env import set_last_pickup_status
                        set_last_pickup_status("patch_creation_failed", err_msg)
                    except Exception:
                        pass
                    try:
                        from app.services.agent_telegram_approval import send_blocker_notification
                        send_blocker_notification(
                            task_id, task_title,
                            reason=err_msg,
                            suggested_action="Re-run investigation or fix patch task creation.",
                        )
                    except Exception as tg_err:
                        logger.warning("strict_patch_creation_failed: Telegram blocker send failed: %s", tg_err)
                    _append_notion_page_comment(
                        task_id,
                        f"[{executed_at}] Strict mode: PATCH task creation failed — staying in-progress. {err_msg}",
                    )
                    return result(
                        True, True, apply_summary,
                        False, False, False, "",
                        False, False, "",
                        "in-progress", False,
                    )
            except Exception as e:
                logger.warning(
                    "execute_prepared_notion_task: strict mode validation error task_id=%s: %s — blocking advance",
                    task_id, e,
                )
                _append_notion_page_comment(
                    task_id,
                    f"[{executed_at}] Strict mode: validation error — staying in-progress. {e}",
                )
                return result(
                    True, True, apply_summary,
                    False, False, False, "",
                    False, False, "",
                    "in-progress", False,
                )
        inv_ok = update_notion_task_status(task_id, "investigation-complete")
        logger.info(
            "execute_prepared_notion_task: extended lifecycle → investigation-complete "
            "task_id=%s status_updated=%s",
            task_id, inv_ok,
        )
        exec_msg = summarize_execution_result(True, apply_summary)
        _append_notion_page_comment(
            task_id,
            f"[{executed_at}] {exec_msg}\n"
            "Investigation complete — advancing to ready-for-patch. No approval until release-candidate-ready.",
        )
        # No approval here — single approval only when release-candidate-ready (after patching + verification)
        # Auto-advance to ready-for-patch
        try:
            from app.services.notion_tasks import TASK_STATUS_READY_FOR_PATCH
            patch_ok = update_notion_task_status(
                task_id, TASK_STATUS_READY_FOR_PATCH,
                append_comment=f"[{executed_at}] Auto-advanced to ready-for-patch. Scheduler will run validation.",
            )
            logger.info(
                "execute_prepared_notion_task: auto-advanced to ready-for-patch task_id=%s ok=%s",
                task_id, patch_ok,
            )
        except Exception as exc:
            logger.warning(
                "execute_prepared_notion_task: auto-advance to ready-for-patch failed task_id=%s: %s",
                task_id, exc,
            )
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "extended_investigation_complete",
                task_id=task_id,
                task_title=task_title,
                details={"status": "ready-for-patch", "auto_advanced": True},
            )
        except Exception:
            pass
        return result(
            True, True, apply_summary,
            False, False, False, "",
            False, False, "",
            "ready-for-patch", True,
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
        validation_ok, validation_summary, _ = _run_callback(prepared_task, validate_fn, "validate")
        if not validation_ok:
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event("validation_failed", task_id=task_id, task_title=task_title, details={"summary": validation_summary})
            except Exception as e:
                logger.debug("log_agent_event(validation_failed) failed: %s", e)
            msg = summarize_validation_result(False, validation_summary)
            _append_notion_page_comment(task_id, f"[{executed_at}] {msg}")
            logger.warning("execute_prepared_notion_task: validation failed task_id=%s summary=%s", task_id, validation_summary)
            _record_test_gate_result(task_id, validation_attempted, False, validation_summary, "testing")
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

        # ----- Extended lifecycle gate: ready-for-deploy -----
        # Record the test result and advance to ready-for-deploy.  The
        # deploy_approve handler checks the test gate, moves the
        # task to deploying, and can trigger a smoke check.
        if use_extended_lifecycle:
            gate_ok = False
            gate_advanced = False
            try:
                from app.services.task_test_gate import record_test_result, test_outcome_from_validation
                gate_outcome, gate_summary = test_outcome_from_validation(True, True, validation_summary)
                gate = record_test_result(
                    task_id, gate_outcome,
                    summary=gate_summary,
                    advance_on_pass=True,
                    current_status="testing",
                )
                gate_ok = gate.get("ok", False)
                gate_advanced = gate.get("advanced", False)
                logger.info(
                    "execute_prepared_notion_task: extended test gate task_id=%s "
                    "ok=%s advanced=%s metadata_ok=%s",
                    task_id, gate_ok, gate_advanced, gate.get("metadata_ok"),
                )
            except Exception as exc:
                logger.error(
                    "execute_prepared_notion_task: extended test gate raised — "
                    "task will NOT advance to deploy approval task_id=%s: %s",
                    task_id, exc,
                )

            if not gate_ok or not gate_advanced:
                logger.warning(
                    "execute_prepared_notion_task: deploy gate not satisfied — "
                    "task stays in testing task_id=%s gate_ok=%s gate_advanced=%s",
                    task_id, gate_ok, gate_advanced,
                )
                _append_notion_page_comment(
                    task_id,
                    f"[{executed_at}] Validation passed but Test Status metadata "
                    "could not be persisted to Notion. Task stays in testing — "
                    "deploy approval deferred until metadata is confirmed.",
                )
                return result(
                    True, True, apply_summary,
                    testing_updated, True, True, validation_summary,
                    False, False, "",
                    "testing", False,
                )

            val_msg = summarize_validation_result(True, validation_summary)
            _append_notion_page_comment(
                task_id,
                f"[{executed_at}] {val_msg}\n"
                "Tests passed — task advanced to ready-for-deploy (approval only at ready-for-patch).",
            )
            # Approval NOT sent here — single trigger point is ready-for-patch only
            logger.info(
                "execute_prepared_notion_task: approval_skipped_reason=not_ready_for_patch "
                "task_id=%s status=ready-for-deploy (approval only at ready-for-patch)",
                task_id,
            )
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "extended_awaiting_deploy_approval",
                    task_id=task_id,
                    task_title=task_title,
                    details={"validation_summary": validation_summary, "approval_skipped_reason": "not_ready_for_patch"},
                )
            except Exception:
                pass
            return result(
                True, True, apply_summary,
                testing_updated, True, True, validation_summary,
                False, False, "",
                "ready-for-deploy", True,
            )

        _record_test_gate_result(task_id, True, True, validation_summary, "testing")
    else:
        _record_test_gate_result(task_id, False, False, "", "testing")
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
        try:
            from app.services.notion_tasks import update_notion_deploy_progress
            update_notion_deploy_progress(task_id, 0)
        except Exception:
            pass
        deployment_ok, deployment_summary, _ = _run_callback(prepared_task, deploy_fn, "deploy")
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
        try:
            from app.services.notion_tasks import update_notion_deploy_progress
            update_notion_deploy_progress(task_id, 20)
        except Exception:
            pass

    # ----- Step 5b: post-deploy smoke check (extended lifecycle only)
    smoke_outcome = _run_post_deploy_smoke_check(task_id, prepared_task)

    if smoke_outcome == "blocked":
        return result(
            True, True, apply_summary,
            testing_updated, True, True, validation_summary,
            deployment_attempted, True, deployment_summary,
            "blocked", False,
        )

    # ----- Step 6 & 7: move to deployed and append final comment
    final_status = "done" if smoke_outcome == "passed" else "deployed"
    deployed_updated = update_notion_task_status(task_id, final_status)
    if deployed_updated:
        logger.info("execute_prepared_notion_task: moved to %s task_id=%s task_title=%r", final_status, task_id, task_title)
    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event("execution_completed", task_id=task_id, task_title=task_title, details={"final_status": final_status})
    except Exception as e:
        logger.debug("log_agent_event(execution_completed) failed: %s", e)
    smoke_note = f" Smoke check: {smoke_outcome}." if smoke_outcome else ""
    final_comment = f"[{executed_at}] Validation passed. Deployment: {deployment_summary}.{smoke_note} Status set to {final_status}."
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
        final_status, True,
    )


# ---------------------------------------------------------------------------
# Extended lifecycle continuation: ready-for-patch → patching → validation
# ---------------------------------------------------------------------------


def advance_ready_for_patch_task(task_id: str) -> dict[str, Any]:
    """Continue the extended lifecycle for a task approved for patching.

    Called by the scheduler when it finds tasks in ``ready-for-patch``.
    The sequence is:

        ready-for-patch → patching → run validate_fn (and optional cursor bridge)
            → if passed:  ready-for-deploy + single Telegram deploy approval
            → if failed:  stays in patching or needs-revision (no approval sent)

    This function does **not** re-run the apply step — the investigation
    artifacts already exist from the first executor run.  It only runs
    validation to verify those artifacts and then gates on human deploy
    approval.

    Returns a structured dict.  Never raises.
    """
    task_id = (task_id or "").strip()
    ts = _utc_now_iso()

    def _result(ok: bool, stage: str, summary: str, final_status: str = "") -> dict[str, Any]:
        return {
            "ok": ok,
            "task_id": task_id,
            "stage": stage,
            "summary": summary,
            "final_status": final_status,
            "timestamp": ts,
        }

    if not task_id:
        return _result(False, "init", "empty task_id")

    # --- 1. Read the task from Notion ---
    try:
        from app.services.notion_task_reader import get_notion_task_by_id
        task = get_notion_task_by_id(task_id)
    except Exception as exc:
        logger.warning("advance_ready_for_patch_task: Notion read failed task_id=%s: %s", task_id, exc)
        return _result(False, "read", str(exc))

    if not task:
        logger.warning("advance_ready_for_patch_task: task not found task_id=%s", task_id)
        return _result(False, "read", "task not found in Notion")

    task_title = str(task.get("task") or "").strip()
    current_status = str(task.get("status") or "").strip().lower()

    _resumable_statuses = ("ready-for-patch", "patching")
    if current_status not in _resumable_statuses:
        logger.info(
            "advance_ready_for_patch_task: skipping task_id=%s status=%s (expected one of %s)",
            task_id, current_status, _resumable_statuses,
        )
        return _result(False, "status_check", f"status is {current_status}, not in {_resumable_statuses}")

    logger.info(
        "advance_ready_for_patch_task: starting continuation task_id=%s title=%r status=%s",
        task_id, task_title, current_status,
    )

    # --- 1b. Infer repo_area early (used by cursor bridge and release approval) ---
    repo_area = infer_repo_area_for_task(task)

    # --- 2. Move to patching (skip if already there) ---
    if current_status == "patching":
        logger.info("advance_ready_for_patch_task: already in patching, skipping status move task_id=%s", task_id)
    else:
        patching_ok = update_notion_task_status(task_id, "patching")
        if not patching_ok:
            logger.warning("advance_ready_for_patch_task: failed to move to patching task_id=%s", task_id)
            return _result(False, "patching", "Notion status update to patching failed")
        logger.info("advance_ready_for_patch_task: moved to patching task_id=%s", task_id)

    # --- 2b. Cursor bridge: when handoff exists, bridge enabled, scheduler auto-run, and approval OK ---
    from app.services.cursor_execution_bridge import (
        is_bridge_enabled,
        is_bridge_require_approval,
        run_bridge_phase2,
        scheduler_should_auto_run_cursor_bridge,
        task_has_patch_approval,
    )
    from app.services.patch_proof import cursor_bridge_required_for_task

    _bridge_auto = scheduler_should_auto_run_cursor_bridge()
    if _bridge_auto:
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event("cursor_bridge_auto_attempt", task_id=task_id, task_title=task_title, details={})
        except Exception:
            pass
        try:
            from app.services._paths import get_writable_cursor_handoffs_dir
            handoff_path = get_writable_cursor_handoffs_dir() / f"cursor-handoff-{task_id}.md"
            _need_bridge, _bridge_reason = cursor_bridge_required_for_task(task, task_id)
            _approval_ok = (not is_bridge_require_approval()) or task_has_patch_approval(task_id)
            # Ensure handoff exists when bridge is needed; auto-generate if missing
            if _need_bridge and not handoff_path.exists():
                from app.services.cursor_execution_bridge import ensure_handoff_file_for_bridge
                ok_handoff, handoff_err = ensure_handoff_file_for_bridge(task_id)
                if not ok_handoff:
                    logger.warning(
                        "advance_ready_for_patch_task: handoff missing, auto-gen failed task_id=%s: %s",
                        task_id, handoff_err,
                    )
                    _append_notion_page_comment(
                        task_id,
                        f"[{ts}] Cursor handoff required but missing and auto-generation failed: {handoff_err}. "
                        "Use 'Run Cursor Bridge' in Telegram after creating handoff manually, or re-run investigation.",
                    )
            if (
                handoff_path.exists()
                and is_bridge_enabled()
                and _need_bridge
                and _approval_ok
            ):
                logger.info("advance_ready_for_patch_task: cursor handoff found, running bridge task_id=%s", task_id)
                bridge_result = run_bridge_phase2(
                    task_id=task_id,
                    ingest=True,
                    create_pr=False,
                    current_status="patching",
                    execution_context="scheduler",
                )
                if bridge_result.get("ok") and bridge_result.get("tests_ok"):
                    ingest_res = bridge_result.get("ingest") or {}
                    if ingest_res.get("gate_result", {}).get("advanced"):
                        try:
                            from app.services.notion_tasks import TASK_STATUS_RELEASE_CANDIDATE_READY
                            update_notion_task_status(
                                task_id, TASK_STATUS_RELEASE_CANDIDATE_READY,
                                append_comment=f"[{ts}] Cursor bridge: apply + tests passed — ready for deploy approval.",
                            )
                        except Exception as status_exc:
                            logger.warning(
                                "advance_ready_for_patch_task: failed to set ready-for-deploy after bridge task_id=%s: %s",
                                task_id, status_exc,
                            )
                        _append_notion_page_comment(
                            task_id,
                            f"[{ts}] Cursor bridge: apply + tests passed — release candidate ready.",
                        )
                        # Single approval when release-candidate-ready
                        try:
                            from app.services.agent_telegram_approval import send_release_candidate_approval
                            pv = str((task or {}).get("proposed_version") or "").strip()
                            tg = send_release_candidate_approval(
                                task_id, task_title,
                                test_summary="Cursor bridge: apply + tests passed",
                                sections=None, task=task, repo_area=repo_area,
                                proposed_version=pv,
                            )
                            logger.info(
                                "advance_ready_for_patch_task: send_release_candidate_approval "
                                "task_id=%s sent=%s dedup_write_failed=%s (cursor bridge path)",
                                task_id, tg.get("sent"), tg.get("dedup_write_failed", False),
                            )
                        except Exception as exc:
                            logger.warning(
                                "advance_ready_for_patch_task: send_release_candidate_approval failed task_id=%s: %s",
                                task_id, exc,
                            )
                        try:
                            from app.services.agent_activity_log import log_agent_event
                            log_agent_event("cursor_bridge_auto_success", task_id=task_id, task_title=task_title, details={"bridge_ok": True})
                        except Exception:
                            pass
                        return _result(True, "cursor_bridge", "bridge apply + tests passed", "release-candidate-ready")
                else:
                    err = bridge_result.get("error") or ""
                    if not err:
                        err = (
                            "invoke or tests did not pass"
                            if not bridge_result.get("tests_ok", True)
                            else "bridge failed"
                        )
                    logger.warning("advance_ready_for_patch_task: cursor bridge failed task_id=%s: %s", task_id, err)
                    _append_notion_page_comment(
                        task_id,
                        f"[{ts}] Cursor bridge ran but did not pass: {err[:200]}. Task stays in patching.",
                    )
                    return _result(False, "cursor_bridge", err, "patching")
            elif (
                handoff_path.exists()
                and is_bridge_enabled()
                and _need_bridge
                and not _approval_ok
            ):
                logger.info(
                    "advance_ready_for_patch_task: bridge skipped (awaiting patch approval) task_id=%s",
                    task_id,
                )
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event(
                        "cursor_bridge_skipped",
                        task_id=task_id,
                        task_title=task_title,
                        details={"reason": "CURSOR_BRIDGE_REQUIRE_APPROVAL: no patch_approved event"},
                    )
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("advance_ready_for_patch_task: cursor bridge branch raised task_id=%s: %s", task_id, exc)
    else:
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "cursor_bridge_skipped",
                task_id=task_id,
                task_title=task_title,
                details={
                    "reason": "scheduler_auto_bridge_off",
                    "hint": "Set CURSOR_BRIDGE_AUTO_IN_ADVANCE=true to opt in; requires CURSOR_BRIDGE_ENABLED=true",
                },
            )
        except Exception:
            pass

    # --- 3. Reconstruct a minimal prepared_task for callback selection ---
    prepared_task: dict[str, Any] = {
        "task": task,
        "repo_area": repo_area,
        "claim": {"status_updated": True},
        "_use_extended_lifecycle": True,
    }

    # --- 4. Re-select callbacks to obtain validate_fn ---
    try:
        select_fn = _get_callbacks_selector()
        callback_selection = select_fn(prepared_task)
    except Exception as exc:
        logger.warning("advance_ready_for_patch_task: callback selection failed task_id=%s: %s", task_id, exc)
        _append_notion_page_comment(task_id, f"[{ts}] Callback re-selection failed during patching: {exc}")
        return _result(False, "callback_selection", str(exc), "patching")

    validate_fn = callback_selection.get("validate_fn")
    if validate_fn is None:
        logger.info("advance_ready_for_patch_task: no validate_fn — leaving in patching task_id=%s", task_id)
        _append_notion_page_comment(
            task_id,
            f"[{ts}] No validation callback available. Task stays in patching for manual validation.",
        )
        return _result(True, "validation", "no validate_fn available", "patching")

    # --- 5. Run validation ---
    val_ok, val_summary, _ = _run_callback(prepared_task, validate_fn, "validate")

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "patch_validation_completed",
            task_id=task_id,
            task_title=task_title,
            details={"passed": val_ok, "summary": val_summary},
        )
    except Exception:
        pass

    if not val_ok:
        logger.warning(
            "advance_ready_for_patch_task: validation failed task_id=%s summary=%s",
            task_id, val_summary,
        )
        _append_notion_page_comment(
            task_id,
            f"[{ts}] {summarize_validation_result(False, val_summary)}\n"
            "Task stays in patching — manual fix or re-investigation required.",
        )
        try:
            from app.services.task_test_gate import record_test_result, test_outcome_from_validation
            outcome, summary = test_outcome_from_validation(True, False, val_summary)
            record_test_result(task_id, outcome, summary=summary, advance_on_pass=False, current_status="patching")
        except Exception:
            pass
        return _result(False, "validation", val_summary, "patching")

    logger.info("advance_ready_for_patch_task: validation passed task_id=%s", task_id)

    # --- 5b. Solution verification: does output address the task requirements? ---
    # Default: enabled. Set ATP_SOLUTION_VERIFICATION_ENABLED=false to disable.
    verification_unavailable_reason: str | None = None
    _verify_raw = (os.environ.get("ATP_SOLUTION_VERIFICATION_ENABLED") or "").strip().lower()
    verify_enabled = _verify_raw not in ("0", "false", "no")
    verify_fn = callback_selection.get("verify_solution_fn")
    if verify_enabled and verify_fn is not None:
        logger.info("verification_started task_id=%s", task_id[:12] if task_id else "?")
        verify_ok, verify_summary, _ = _run_callback(prepared_task, verify_fn, "verify_solution")
        if not verify_ok:
            # Distinguish: verification unavailable (env/config/error) vs verification failed (bad solution)
            _s = (verify_summary or "").lower()
            verification_unavailable = (
                "verification unavailable" in _s or "verification error" in _s
            )
            if verification_unavailable:
                logger.info(
                    "verification_unavailable task_id=%s reason=%s",
                    task_id[:12] if task_id else "?",
                    (verify_summary or "")[:200],
                )
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event(
                        "verification_unavailable",
                        task_id=task_id,
                        task_title=task_title,
                        details={
                            "summary": verify_summary,
                            "verification_unavailable_reason": verify_summary,
                        },
                    )
                except Exception:
                    pass
                verification_unavailable_reason = verify_summary
                # Proceed to deploy approval path — patch is ready; verification skipped due to env
                logger.info(
                    "verification_unavailable: advancing to deploy approval (patch ready, env not configured) task_id=%s",
                    task_id[:12] if task_id else "?",
                )
            else:
                # Actual verification failure — solution does not address task
                logger.warning(
                    "verification_failed task_id=%s summary=%s",
                    task_id[:12] if task_id else "?", verify_summary[:200] if verify_summary else "?",
                )
                try:
                    from app.services.agent_activity_log import log_agent_event
                    log_agent_event(
                        "verification_failed",
                        task_id=task_id,
                        task_title=task_title,
                        details={"summary": verify_summary},
                    )
                except Exception:
                    pass
                try:
                    from app.services.task_status_transition import safe_transition_to_needs_revision
                    revision_reason = f"Solution verification failed: {verify_summary}"[:400]
                    status_ok = safe_transition_to_needs_revision(
                        task_id,
                        revision_reason=revision_reason,
                        verify_summary=verify_summary,
                        from_status="ready-for-patch",
                        task_title=task_title,
                        append_comment=(
                            f"[{ts}] Solution verification FAILED — output does not address task requirements.\n"
                            f"Feedback: {verify_summary}\n\n"
                            "Use the Re-investigate button in Telegram to iterate with this feedback."
                        ),
                    )
                    if status_ok:
                        try:
                            from app.services.needs_revision_processor import update_task_on_needs_revision
                            update_task_on_needs_revision(task_id, revision_reason)
                        except Exception as nr_e:
                            logger.debug("advance_ready_for_patch_task: update_task_on_needs_revision failed %s", nr_e)
                        try:
                            from app.services.agent_telegram_approval import clear_task_approval_record
                            clear_task_approval_record(task_id)
                        except Exception as clr_exc:
                            logger.warning(
                                "advance_ready_for_patch_task: clear_task_approval_record failed task_id=%s: %s",
                                task_id, clr_exc,
                            )
                        try:
                            from app.services.agent_telegram_approval import send_needs_revision_reinvestigate
                            send_needs_revision_reinvestigate(
                                task_id, task_title,
                                feedback=verify_summary,
                            )
                        except Exception as tg_exc:
                            logger.warning(
                                "advance_ready_for_patch_task: send_needs_revision_reinvestigate failed task_id=%s: %s",
                                task_id, tg_exc,
                            )
                except Exception as exc:
                    logger.warning("advance_ready_for_patch_task: failed to move to needs-revision task_id=%s: %s", task_id, exc)
                return _result(False, "solution_verification", verify_summary, "needs-revision")
        else:
            logger.info("verification_passed task_id=%s", task_id[:12] if task_id else "?")
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "verification_passed",
                    task_id=task_id,
                    task_title=task_title,
                    details={"summary": verify_summary},
                )
            except Exception:
                pass

    # --- 5c. Patch proof gate: code-fix tasks require Cursor Bridge before ready-for-deploy ---
    # Investigation is not implementation. Deploy approval blocked until patch evidence exists.
    try:
        from app.services.patch_proof import cursor_bridge_required_for_task
        bridge_required, bridge_reason = cursor_bridge_required_for_task(task, task_id)
        if bridge_required:
            logger.info(
                "cursor_bridge_required task_id=%s reason=%s — blocking advance to ready-for-deploy",
                task_id[:12] if task_id else "?",
                bridge_reason,
            )
            try:
                from app.services.agent_activity_log import log_agent_event
                log_agent_event(
                    "deploy_blocked_no_patch",
                    task_id=task_id,
                    task_title=task_title,
                    details={"reason": bridge_reason},
                )
            except Exception:
                pass
            _append_notion_page_comment(
                task_id,
                f"[{ts}] Validation passed but patch not yet applied. "
                "Code-fix tasks require Cursor Bridge to run before deploy approval. "
                "Use 'Run Cursor Bridge' in Telegram to apply the fix.",
            )
            try:
                from app.services.agent_telegram_approval import send_patch_not_applied_message
                tg = send_patch_not_applied_message(task_id, task_title)
                logger.info(
                    "advance_ready_for_patch_task: send_patch_not_applied_message task_id=%s sent=%s",
                    task_id, tg.get("sent"),
                )
            except Exception as exc:
                logger.warning(
                    "advance_ready_for_patch_task: send_patch_not_applied_message failed task_id=%s: %s",
                    task_id, exc,
                )
            return _result(
                False,
                "patch_proof_gate",
                f"Cursor Bridge required ({bridge_reason}) — no deploy until patch applied",
                "patching",
            )
        logger.info(
            "deploy_allowed_with_patch task_id=%s reason=%s",
            task_id[:12] if task_id else "?",
            bridge_reason,
        )
        try:
            from app.services.agent_activity_log import log_agent_event
            log_agent_event(
                "deploy_allowed_with_patch",
                task_id=task_id,
                task_title=task_title,
                details={"reason": bridge_reason},
            )
        except Exception:
            pass
    except Exception as exc:
        logger.warning(
            "advance_ready_for_patch_task: patch_proof gate check failed task_id=%s: %s — allowing advance (fail-open for non-code tasks)",
            task_id, exc,
        )

    # --- 6. Record test gate and advance to awaiting-deploy-approval ---
    gate_ok = False
    gate_advanced = False
    try:
        from app.services.task_test_gate import record_test_result, test_outcome_from_validation
        outcome, summary = test_outcome_from_validation(True, True, val_summary)
        gate = record_test_result(
            task_id, outcome,
            summary=summary,
            advance_on_pass=True,
            current_status="patching",
        )
        gate_ok = gate.get("ok", False)
        gate_advanced = gate.get("advanced", False)
        logger.info(
            "advance_ready_for_patch_task: test gate task_id=%s ok=%s advanced=%s metadata_ok=%s",
            task_id, gate_ok, gate_advanced, gate.get("metadata_ok"),
        )
    except Exception as exc:
        logger.error(
            "advance_ready_for_patch_task: test gate raised — task will NOT "
            "advance to deploy approval task_id=%s: %s",
            task_id, exc,
        )

    if not gate_ok or not gate_advanced:
        logger.warning(
            "advance_ready_for_patch_task: deploy gate not satisfied — "
            "task stays in patching task_id=%s gate_ok=%s gate_advanced=%s",
            task_id, gate_ok, gate_advanced,
        )
        _append_notion_page_comment(
            task_id,
            f"[{ts}] Validation passed but Test Status metadata could not be "
            "persisted to Notion. Task stays in patching — ready-for-deploy "
            "deferred until metadata is confirmed.",
        )
        return _result(False, "metadata_persist", "Test Status not written — advancement blocked", "patching")

    logger.info("release_candidate_ready_set task_id=%s", task_id[:12] if task_id else "?")
    # --- 6b. Move to release-candidate-ready (record_test_result already advanced status) ---
    if verification_unavailable_reason:
        _append_notion_page_comment(
            task_id,
            f"[{ts}] {summarize_validation_result(True, val_summary)}\n"
            f"Verification unavailable ({verification_unavailable_reason[:100]}). "
            "Patch ready — single approval sent.",
        )
    else:
        _append_notion_page_comment(
            task_id,
            f"[{ts}] {summarize_validation_result(True, val_summary)}\n"
            "Tests passed — release candidate ready. Single approval sent.",
        )

    # --- 7. Single approval ONLY when release-candidate-ready ---
    try:
        from app.services.agent_telegram_approval import send_release_candidate_approval
        pv = str((task or {}).get("proposed_version") or "").strip()
        tg = send_release_candidate_approval(
            task_id,
            task_title,
            test_summary=val_summary,
            sections=None,
            task=task,
            repo_area=repo_area,
            verification_unavailable_reason=verification_unavailable_reason,
            proposed_version=pv,
        )
        logger.info(
            "advance_ready_for_patch_task: send_release_candidate_approval "
            "task_id=%s sent=%s message_id=%s dedup_write_failed=%s status=release-candidate-ready",
            task_id, tg.get("sent"), tg.get("message_id"), tg.get("dedup_write_failed", False),
        )
    except Exception as exc:
        logger.warning(
            "advance_ready_for_patch_task: send_release_candidate_approval failed task_id=%s: %s",
            task_id, exc,
        )

    try:
        from app.services.agent_activity_log import log_agent_event
        log_agent_event(
            "release_candidate_approval_sent",
            task_id=task_id,
            task_title=task_title,
            details={"validation_summary": val_summary},
        )
    except Exception:
        pass

    return _result(True, "release_candidate_approval_sent", val_summary, "release-candidate-ready")

