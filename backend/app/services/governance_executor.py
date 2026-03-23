"""
Approved-only executor for a small whitelist of PROD actions.

Every step runs only after is_manifest_approved_and_valid(..., expected_commands=...).
No arbitrary shell — explicit action types only.
"""

from __future__ import annotations

import json
import logging
import subprocess
from typing import Any
from urllib.parse import urlparse

import httpx
from sqlalchemy.orm import Session

from app.services._paths import workspace_root
from app.models.governance_models import GovernanceManifest, GovernanceTask
from app.services.governance_service import (
    ST_APPLYING,
    ST_AWAITING_APPROVAL,
    ST_COMPLETED,
    ST_FAILED,
    ST_VALIDATING,
    emit_action_event,
    emit_error_event,
    emit_result_event,
    is_manifest_approved_and_valid,
    transition_task_state,
)
from app.services.governance_timeline import TIMELINE_SIGNAL_BLOCKED, TIMELINE_SIGNAL_FAILED

logger = logging.getLogger(__name__)

ALLOWED_COMPOSE_PROFILES = frozenset({"aws", "local"})
ALLOWED_COMPOSE_SERVICES = frozenset({"backend-aws"})
ALLOWED_COMPOSE_FILES = frozenset({"docker-compose.yml"})


def _health_url_allowed(url: str) -> bool:
    try:
        p = urlparse(url.strip())
    except Exception:
        return False
    if p.scheme != "http":
        return False
    if p.hostname not in ("127.0.0.1", "localhost"):
        return False
    if p.port not in (8000, 8002):
        return False
    path = p.path or "/"
    # Narrow: literal /health or any path segment containing "health" (e.g. /api/v1/health)
    return path == "/health" or path.startswith("/health") or "/health" in path


def _execute_step(
    step: dict[str, Any],
    idx: int,
    *,
    execution_actor_id: str = "",
) -> tuple[bool, str, dict[str, Any] | None]:
    stype = (step.get("type") or "").strip()
    if stype == "noop":
        return True, step.get("message") or "noop", None

    if stype == "docker_compose_restart":
        profile = (step.get("profile") or "").strip()
        service = (step.get("service") or "").strip()
        compose_rel = (step.get("compose_relative") or "docker-compose.yml").strip()
        if profile not in ALLOWED_COMPOSE_PROFILES:
            return False, f"profile not allowed: {profile!r}", None
        if service not in ALLOWED_COMPOSE_SERVICES:
            return False, f"service not allowed: {service!r}", None
        if compose_rel not in ALLOWED_COMPOSE_FILES:
            return False, f"compose file not allowed: {compose_rel!r}", None
        root = workspace_root()
        cmd = [
            "docker",
            "compose",
            "-f",
            compose_rel,
            "--profile",
            profile,
            "restart",
            service,
        ]
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=600,
            )
        except Exception as e:
            return False, f"docker compose restart failed: {e}", None
        if proc.returncode != 0:
            return False, (proc.stderr or proc.stdout or "restart failed")[:2000], None
        return True, "docker compose restart ok", None

    if stype == "agent_deploy_bundle":
        nid = (step.get("notion_task_id") or "").strip()
        if not nid:
            return False, "agent_deploy_bundle missing notion_task_id", None
        who = (execution_actor_id or "governance_executor").strip() or "governance_executor"
        extra: dict[str, Any] = {}
        try:
            from app.services.agent_strategy_patch import apply_prepared_strategy_patch_after_approval
            from app.services.deploy_trigger import trigger_deploy_workflow

            patch_result = apply_prepared_strategy_patch_after_approval(nid)
            extra["strategy_patch"] = patch_result
            deploy_result = trigger_deploy_workflow(task_id=nid, triggered_by=who)
            extra["deploy_workflow"] = deploy_result
            if not deploy_result.get("ok"):
                err = deploy_result.get("error") or deploy_result.get("summary") or "deploy failed"
                return False, str(err)[:2000], extra
            summary = str(deploy_result.get("summary") or "workflow dispatched")[:500]
            return True, f"agent_deploy_bundle ok: {summary}", extra
        except Exception as e:
            logger.exception("agent_deploy_bundle failed notion_task_id=%s", nid[:12])
            return False, f"agent_deploy_bundle error: {e}", extra

    if stype == "agent_execute_prepared_pipeline":
        nid = (step.get("notion_task_id") or "").strip()
        if not nid:
            return False, "agent_execute_prepared_pipeline missing notion_task_id", None
        extra: dict[str, Any] = {}
        try:
            from app.services.agent_telegram_approval import load_prepared_bundle_for_execution
            from app.services.agent_task_executor import execute_prepared_task_if_approved

            bundle = load_prepared_bundle_for_execution(nid)
            if not bundle:
                return False, "no approved prepared bundle for pipeline (DB/agent_approval_states)", extra
            pt = bundle.get("prepared_task")
            if not isinstance(pt, dict):
                return False, "prepared_task missing from bundle", extra
            pt = dict(pt)
            pt["_governance_pipeline_internal"] = True
            bundle = dict(bundle)
            bundle["prepared_task"] = pt
            exec_out = execute_prepared_task_if_approved(bundle, approved=True)
            extra["telegram_wrapper"] = {
                "approval_required": exec_out.get("approval_required"),
                "execution_skipped": exec_out.get("execution_skipped"),
            }
            er = exec_out.get("execution_result")
            extra["execution_result"] = er
            if exec_out.get("execution_skipped"):
                return False, exec_out.get("reason") or "execution skipped inside pipeline", extra
            if isinstance(er, dict) and er.get("success"):
                return True, "agent_execute_prepared_pipeline completed", extra
            summ = ""
            if isinstance(er, dict):
                summ = str((er.get("apply") or {}).get("summary") or er.get("final_status") or "")
            return False, (summ or "pipeline execution failed")[:2000], extra
        except Exception as e:
            logger.exception("agent_execute_prepared_pipeline failed notion_task_id=%s", nid[:12])
            return False, f"agent_execute_prepared_pipeline error: {e}", extra

    if stype in ("http_health", "validate_http"):
        url = (step.get("url") or "").strip()
        if not _health_url_allowed(url):
            return False, f"url not allowed: {url!r}", None
        try:
            with httpx.Client(timeout=20.0) as client:
                r = client.get(url)
        except Exception as e:
            return False, f"http get failed: {e}", None
        if r.status_code >= 400:
            return False, f"http status {r.status_code}", None
        return True, f"http ok {r.status_code}", None

    return False, f"unknown action type: {stype!r}", None


def execute_governed_manifest(
    db: Session,
    *,
    task_id: str,
    manifest_id: str,
    actor_type: str = "system",
    actor_id: str = "governance_executor",
) -> dict[str, Any]:
    """
    Verify approval + digest, transition lifecycle, run whitelisted steps.
    Returns a result dict (never raises for business logic — callers commit/rollback).
    """
    tid = (task_id or "").strip()
    mid = (manifest_id or "").strip()
    out: dict[str, Any] = {"success": False, "task_id": tid, "manifest_id": mid, "steps": []}

    task = db.query(GovernanceTask).filter(GovernanceTask.task_id == tid).first()
    if not task:
        out["error"] = "task not found"
        return out

    mrow = db.query(GovernanceManifest).filter(GovernanceManifest.manifest_id == mid).first()
    if not mrow or mrow.task_id != tid:
        out["error"] = "manifest not found or task mismatch"
        return out

    try:
        commands: list[dict[str, Any]] = json.loads(mrow.commands_json or "[]")
    except json.JSONDecodeError:
        commands = []
    if not isinstance(commands, list):
        commands = []

    ok, reason = is_manifest_approved_and_valid(db, mid, expected_commands=commands)
    if not ok:
        out["error"] = reason
        emit_error_event(
            db,
            task_id=tid,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            phase="pre_execute",
            message=reason,
            manifest_id=mid,
            signal_hint=TIMELINE_SIGNAL_BLOCKED,
        )
        return out

    st = (task.status or "").strip()
    if st != ST_AWAITING_APPROVAL:
        out["error"] = f"task not in {ST_AWAITING_APPROVAL!r} (is {st!r})"
        emit_error_event(
            db,
            task_id=tid,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            phase="pre_execute",
            message=out["error"],
            manifest_id=mid,
            signal_hint=TIMELINE_SIGNAL_BLOCKED,
        )
        return out

    try:
        transition_task_state(
            db,
            task_id=tid,
            to_state=ST_APPLYING,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            reason=f"execute manifest {mid}",
            send_telegram=False,
        )
    except ValueError as e:
        out["error"] = str(e)
        return out

    for i, step in enumerate(commands):
        if not isinstance(step, dict):
            emit_error_event(
                db,
                task_id=tid,
                actor_type=actor_type,
                actor_id=actor_id,
                environment="prod",
                phase="applying",
                message=f"step {i} not an object",
                signal_hint=TIMELINE_SIGNAL_FAILED,
            )
            transition_task_state(
                db,
                task_id=tid,
                to_state=ST_FAILED,
                actor_type=actor_type,
                actor_id=actor_id,
                environment="prod",
                reason="bad step shape",
                send_telegram=False,
            )
            out["error"] = "invalid step"
            return out

        emit_action_event(
            db,
            task_id=tid,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            name=f"step_{i}_start",
            status="started",
            target=(step.get("type") or "?")[:80],
            manifest_id=mid,
        )
        step_ok, step_msg, step_extra = _execute_step(
            step, i, execution_actor_id=(actor_id or "").strip()
        )
        out["steps"].append({"index": i, "ok": step_ok, "message": step_msg})
        if step_extra:
            st_t = (step.get("type") or "").strip()
            if st_t == "agent_deploy_bundle":
                out["agent_deploy_bundle"] = step_extra
            elif st_t == "agent_execute_prepared_pipeline":
                out["agent_execute_prepared_pipeline"] = step_extra
                er = step_extra.get("execution_result")
                if isinstance(er, dict):
                    out["agent_execute_prepared_pipeline_result"] = er
        emit_action_event(
            db,
            task_id=tid,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            name=f"step_{i}_end",
            status="completed" if step_ok else "failed",
            target=(step.get("type") or "?")[:80],
            detail=step_msg[:500],
        )
        if not step_ok:
            emit_error_event(
                db,
                task_id=tid,
                actor_type=actor_type,
                actor_id=actor_id,
                environment="prod",
                phase="applying",
                message=step_msg,
                step_index=i,
                signal_hint=TIMELINE_SIGNAL_FAILED,
            )
            transition_task_state(
                db,
                task_id=tid,
                to_state=ST_FAILED,
                actor_type=actor_type,
                actor_id=actor_id,
                environment="prod",
                reason=step_msg[:200],
                send_telegram=False,
            )
            emit_result_event(
                db,
                task_id=tid,
                actor_type=actor_type,
                actor_id=actor_id,
                environment="prod",
                outcome="failed",
                summary=step_msg[:500],
                signal_hint=TIMELINE_SIGNAL_FAILED,
            )
            try:
                from app.services.governance_telegram import send_governance_telegram_summary
                send_governance_telegram_summary(
                    "failed",
                    task_id=tid,
                    manifest_id=mid,
                    lines=[step_msg[:200]],
                )
            except Exception:
                pass
            out["error"] = step_msg
            return out

    try:
        transition_task_state(
            db,
            task_id=tid,
            to_state=ST_VALIDATING,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            reason="steps complete",
            send_telegram=False,
        )
        transition_task_state(
            db,
            task_id=tid,
            to_state=ST_COMPLETED,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            reason="executor finished",
            send_telegram=False,
        )
    except ValueError as e:
        logger.warning("governance executor lifecycle tail failed: %s", e)
        emit_error_event(
            db,
            task_id=tid,
            actor_type=actor_type,
            actor_id=actor_id,
            environment="prod",
            phase="validating",
            message=str(e),
            signal_hint=TIMELINE_SIGNAL_FAILED,
        )

    emit_result_event(
        db,
        task_id=tid,
        actor_type=actor_type,
        actor_id=actor_id,
        environment="prod",
        outcome="success",
        summary=f"manifest {mid} executed ({len(commands)} steps)",
    )
    try:
        from app.services.governance_telegram import send_governance_telegram_summary
        send_governance_telegram_summary(
            "completed",
            task_id=tid,
            manifest_id=mid,
            lines=[f"Steps: {len(commands)}"],
        )
    except Exception:
        pass

    out["success"] = True
    return out
