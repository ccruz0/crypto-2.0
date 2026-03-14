"""Agent orchestration status and operations visibility endpoints.

Provides a lightweight read-only view of the scheduler, task
lifecycle, recovery actions, and smoke checks for operational dashboards.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException, Query

logger = logging.getLogger(__name__)

router = APIRouter()


def _verify_agent_token(authorization: str | None = Header(None)) -> None:
    """Verify Bearer token matches OPENCLAW_API_TOKEN. Raises HTTPException if invalid."""
    token = (os.environ.get("OPENCLAW_API_TOKEN") or "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Agent API not configured (OPENCLAW_API_TOKEN)")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Authorization: Bearer <token> required")
    if authorization[7:].strip() != token:
        raise HTTPException(status_code=403, detail="Invalid token")

# Event types for ops visibility
_RECOVERY_EVENT_TYPES = frozenset({
    "recovery_orphan_smoke_attempt",
    "recovery_revalidate_patching_attempt",
    "recovery_missing_artifact_attempt",
})
_FAILED_INVESTIGATION_EVENT_TYPES = frozenset({
    "execution_failed",
    "validation_failed",
})
_SMOKE_CHECK_EVENT_TYPES = frozenset({
    "smoke_check_recorded",
    "webhook_smoke_check",
})


def _count_tasks_by_statuses(statuses: list[str]) -> int:
    try:
        from app.services.notion_task_reader import get_tasks_by_status
        return len(get_tasks_by_status(statuses, max_results=50))
    except Exception as exc:
        logger.debug("routes_agent: get_tasks_by_status(%s) failed: %s", statuses, exc)
        return -1


@router.get("/agent/status")
def agent_status() -> dict[str, Any]:
    """Return a snapshot of the agent orchestration state."""
    from app.services.agent_scheduler import get_scheduler_state

    state = get_scheduler_state()

    pending = _count_tasks_by_statuses([
        "planned", "Planned", "backlog", "Backlog",
        "ready-for-investigation", "Ready for Investigation",
        "blocked", "Blocked",
    ])
    investigation = _count_tasks_by_statuses([
        "investigation", "Investigation",
        "investigation-complete", "Investigation Complete",
    ])
    patch = _count_tasks_by_statuses([
        "ready-for-patch", "Ready for Patch",
        "patching", "Patching",
    ])
    awaiting_deploy = _count_tasks_by_statuses([
        "awaiting-deploy-approval", "Awaiting Deploy Approval",
    ])
    deploying = _count_tasks_by_statuses(["deploying", "Deploying"])

    pending_approvals = 0
    try:
        from app.services.agent_telegram_approval import get_pending_approvals
        pending_approvals = len(get_pending_approvals())
    except Exception as exc:
        logger.debug("routes_agent: get_pending_approvals failed: %s", exc)
        pending_approvals = -1

    return {
        "scheduler_running": state["running"],
        "automation_enabled": state["automation_enabled"],
        "last_scheduler_cycle": state["last_cycle"],
        "scheduler_interval_s": state["interval"],
        "pending_notion_tasks": pending,
        "tasks_in_investigation": investigation,
        "tasks_in_patch_phase": patch,
        "tasks_awaiting_deploy": awaiting_deploy,
        "tasks_deploying": deploying,
        "pending_approvals": pending_approvals,
    }


def _filter_events_by_type(
    events: list[dict[str, Any]],
    event_types: frozenset[str],
    limit: int,
) -> list[dict[str, Any]]:
    """Filter events by type, newest first, up to limit."""
    out: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("event_type") in event_types and len(out) < limit:
            out.append(ev)
    return out


@router.get("/agent/ops/recovery")
def agent_ops_recovery(
    limit: int = Query(20, ge=1, le=100, description="Max recovery events to return"),
) -> dict[str, Any]:
    """Return recent autonomous recovery actions from the activity log."""
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        events = get_recent_agent_events(limit=200)
        recovery = _filter_events_by_type(events, _RECOVERY_EVENT_TYPES, limit)
        return {
            "ok": True,
            "recovery_actions": recovery,
            "count": len(recovery),
        }
    except Exception as exc:
        logger.warning("agent_ops_recovery failed: %s", exc)
        return {"ok": False, "recovery_actions": [], "count": 0, "error": str(exc)}


@router.get("/agent/ops/failed-investigations")
def agent_ops_failed_investigations(
    limit: int = Query(20, ge=1, le=100, description="Max failed events to return"),
) -> dict[str, Any]:
    """Return recent failed investigations (execution_failed, validation_failed) from the activity log."""
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        events = get_recent_agent_events(limit=200)
        failed = _filter_events_by_type(events, _FAILED_INVESTIGATION_EVENT_TYPES, limit)
        return {
            "ok": True,
            "failed_investigations": failed,
            "count": len(failed),
        }
    except Exception as exc:
        logger.warning("agent_ops_failed_investigations failed: %s", exc)
        return {"ok": False, "failed_investigations": [], "count": 0, "error": str(exc)}


@router.get("/agent/ops/active-tasks")
def agent_ops_active_tasks() -> dict[str, Any]:
    """Return tasks currently in patching, deploying, or awaiting-deploy-approval."""
    try:
        from app.services.notion_task_reader import get_tasks_by_status

        patching = get_tasks_by_status(
            ["patching", "Patching", "ready-for-patch", "Ready for Patch"],
            max_results=20,
        )
        deploying = get_tasks_by_status(["deploying", "Deploying"], max_results=10)
        awaiting = get_tasks_by_status(
            ["awaiting-deploy-approval", "Awaiting Deploy Approval"],
            max_results=10,
        )

        def _summarize(t: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": t.get("id"),
                "task": (t.get("task") or "")[:120],
                "status": t.get("status"),
                "priority": t.get("priority"),
            }

        return {
            "ok": True,
            "patching": [_summarize(t) for t in patching],
            "deploying": [_summarize(t) for t in deploying],
            "awaiting_deploy_approval": [_summarize(t) for t in awaiting],
        }
    except Exception as exc:
        logger.warning("agent_ops_active_tasks failed: %s", exc)
        return {
            "ok": False,
            "patching": [],
            "deploying": [],
            "awaiting_deploy_approval": [],
            "error": str(exc),
        }


@router.get("/agent/ops/smoke-checks")
def agent_ops_smoke_checks(
    limit: int = Query(20, ge=1, le=100, description="Max smoke check events to return"),
) -> dict[str, Any]:
    """Return last smoke check outcomes from the activity log."""
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        events = get_recent_agent_events(limit=200)
        smoke = _filter_events_by_type(events, _SMOKE_CHECK_EVENT_TYPES, limit)
        return {
            "ok": True,
            "smoke_checks": smoke,
            "count": len(smoke),
        }
    except Exception as exc:
        logger.warning("agent_ops_smoke_checks failed: %s", exc)
        return {"ok": False, "smoke_checks": [], "count": 0, "error": str(exc)}


@router.post("/agent/run-smoke-check")
def agent_run_smoke_check(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """
    Run post-deploy smoke check for a task in deploying.
    Body: { "task_id": "<notion_page_id>" } — optional; if omitted, uses first task in deploying.
    Advances task to done (pass) or blocked (fail). Same as Telegram Smoke Check button.
    """
    try:
        from app.services.deploy_smoke_check import run_and_record_smoke_check
        from app.services.notion_task_reader import get_tasks_by_status
    except ImportError as e:
        return {"ok": False, "error": str(e)}

    payload = body or {}
    task_id = (payload.get("task_id") or "").strip()
    if not task_id:
        tasks = get_tasks_by_status(["deploying", "Deploying"], max_results=1)
        if not tasks:
            return {"ok": False, "error": "no task_id provided and no task in deploying status"}
        task_id = str(tasks[0].get("id") or "").strip()
        if not task_id:
            return {"ok": False, "error": "no task_id in deploying task"}

    result = run_and_record_smoke_check(
        task_id,
        advance_on_pass=True,
        current_status="deploying",
    )
    return {
        "ok": True,
        "task_id": task_id,
        "outcome": result.get("outcome"),
        "advanced": result.get("advanced"),
        "blocked": result.get("blocked"),
        "summary": result.get("summary", ""),
    }


@router.get("/agent/ops/deploy-tracker")
def agent_ops_deploy_tracker(
    limit: int = Query(10, ge=1, le=50, description="Max deploy entries to return"),
) -> dict[str, Any]:
    """Return recent deploy dispatches from the in-process tracker."""
    try:
        from app.services.deploy_trigger import get_recent_deploys, get_last_deploy_task_id
        deploys = get_recent_deploys(limit=limit)
        last_task_id = get_last_deploy_task_id()
        return {
            "ok": True,
            "recent_deploys": deploys,
            "last_deploy_task_id": last_task_id,
        }
    except Exception as exc:
        logger.warning("agent_ops_deploy_tracker failed: %s", exc)
        return {
            "ok": False,
            "recent_deploys": [],
            "last_deploy_task_id": "",
            "error": str(exc),
        }


# ---------------------------------------------------------------------------
# Cursor Execution Bridge (Phase 1)
# ---------------------------------------------------------------------------

_CURSOR_BRIDGE_EVENT_TYPES = frozenset({
    "cursor_bridge_staging_provisioned",
    "cursor_bridge_staging_failed",
    "cursor_bridge_invoke_start",
    "cursor_bridge_invoke_done",
    "cursor_bridge_invoke_failed",
    "cursor_bridge_invoke_timeout",
    "cursor_bridge_diff_captured",
    "cursor_bridge_diff_empty",
    "cursor_bridge_tests_done",
    "cursor_bridge_tests_failed",
    "cursor_bridge_ingest_done",
    "cursor_bridge_pr_created",
    "cursor_bridge_auto_success",
    "cursor_bridge_telegram_triggered",
})


@router.get("/agent/ops/cursor-bridge-events")
def agent_ops_cursor_bridge_events(
    limit: int = Query(20, ge=1, le=100, description="Max bridge events to return"),
) -> dict[str, Any]:
    """Return recent Cursor bridge events from the activity log."""
    try:
        from app.services.agent_activity_log import get_recent_agent_events
        events = get_recent_agent_events(limit=200)
        bridge = _filter_events_by_type(events, _CURSOR_BRIDGE_EVENT_TYPES, limit)
        return {
            "ok": True,
            "cursor_bridge_events": bridge,
            "count": len(bridge),
        }
    except Exception as exc:
        logger.warning("agent_ops_cursor_bridge_events failed: %s", exc)
        return {"ok": False, "cursor_bridge_events": [], "count": 0, "error": str(exc)}


@router.get("/agent/cursor-bridge/diagnostics")
def agent_cursor_bridge_diagnostics() -> dict[str, Any]:
    """
    Return Cursor bridge readiness diagnostics (env, CLI, staging root, etc.).
    No side effects; safe to call anytime.
    """
    try:
        from app.services.cursor_execution_bridge import get_bridge_diagnostics
        return {"ok": True, **get_bridge_diagnostics()}
    except Exception as exc:
        logger.warning("agent_cursor_bridge_diagnostics failed: %s", exc)
        return {"ok": False, "error": str(exc)}


@router.post("/agent/run-atp-command")
def agent_run_atp_command(
    body: dict[str, Any] = Body(default={}),
    authorization: str | None = Header(None),
) -> dict[str, Any]:
    """
    Run a safe command on the ATP instance via AWS SSM.

    Requires: Authorization: Bearer <OPENCLAW_API_TOKEN> (same as OpenClaw gateway).
    Body: { "command": "docker compose --profile aws ps", "timeout_seconds": 60 }

    Allowed commands: docker compose ps, docker compose logs --tail=N, docker ps,
    curl http://127.0.0.1:8002/ping_fast, curl http://127.0.0.1:8002/api/health,
    df -h /, free -h. Deny: sudo, rm -rf, git push, deploy, etc.
    """
    _verify_agent_token(authorization)
    try:
        from app.services.atp_ssm_runner import run_atp_command
    except ImportError as e:
        return {"ok": False, "error": str(e), "stdout": "", "stderr": ""}

    payload = body or {}
    command = (payload.get("command") or "").strip()
    timeout = int(payload.get("timeout_seconds") or 60)
    if not command:
        raise HTTPException(status_code=400, detail="command required")

    result = run_atp_command(command, timeout_seconds=min(timeout, 120))
    return {
        "ok": result.get("ok", False),
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "status": result.get("status", ""),
        "error": result.get("error"),
    }


@router.get("/agent/atp-instance-info")
def agent_atp_instance_info() -> dict[str, Any]:
    """Return ATP instance metadata and allowed commands (for prompts). No auth required."""
    try:
        from app.services.atp_ssm_runner import get_atp_instance_info
        return {"ok": True, **get_atp_instance_info()}
    except ImportError as e:
        return {"ok": False, "error": str(e)}


@router.post("/agent/cursor-bridge/run")
def agent_cursor_bridge_run(body: dict[str, Any] = Body(default={})) -> dict[str, Any]:
    """
    Run Cursor bridge for a task — provision staging, invoke CLI, capture diff, run tests.

    Body: { "task_id": "<notion_page_id>", "phase": 1|2, "ingest": true|false, "create_pr": true|false } — optional "prompt", "phase" (default 2), "ingest" (default true), "create_pr" (default false), "current_status" (default "patching").
    Phase 1: provision + invoke only. Phase 2: + diff capture + tests + Notion ingestion.
    Requires CURSOR_BRIDGE_ENABLED=true. Handoff must exist at
    docs/agents/cursor-handoffs/cursor-handoff-{task_id}.md unless prompt is provided.
    """
    try:
        from app.services.cursor_execution_bridge import (
            is_bridge_enabled,
            run_bridge_phase1,
            run_bridge_phase2,
        )
    except ImportError as e:
        return {"ok": False, "error": f"cursor_execution_bridge not available: {e}"}

    if not is_bridge_enabled():
        return {"ok": False, "error": "CURSOR_BRIDGE_ENABLED not set (set to true to enable)"}

    payload = body or {}
    task_id = (payload.get("task_id") or "").strip()
    prompt = payload.get("prompt")
    phase = payload.get("phase", 2)
    ingest = payload.get("ingest", True)
    create_pr = payload.get("create_pr", False)
    current_status = (payload.get("current_status") or "patching").strip()

    if not task_id:
        return {"ok": False, "error": "task_id required"}

    if phase == 1:
        result = run_bridge_phase1(task_id=task_id, prompt=prompt)
    else:
        result = run_bridge_phase2(
            task_id=task_id,
            prompt=prompt,
            ingest=ingest,
            create_pr=create_pr,
            current_status=current_status,
        )
    return result
