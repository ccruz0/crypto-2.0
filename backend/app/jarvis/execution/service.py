"""Jarvis Phase 3 task execution orchestration service."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.jarvis.agents.executor_agent import execute_plan
from app.jarvis.agents.planner_agent import build_plan, plan_to_dict
from app.jarvis.agents.repository_agent import investigate_objective
from app.jarvis.artifacts.storage import create_artifact
from app.jarvis.execution.audit import list_execution_log, log_execution_event
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    create_execution_task,
    get_execution_task,
    list_approvals,
    list_execution_tasks,
    record_approval,
    transition_task_status,
)
from app.jarvis.execution.safety import SafetyLevel, is_forbidden, merge_safety_levels
from app.jarvis.execution.schemas import JarvisExecutionPlan
from app.jarvis.mvp.config import jarvis_dry_run_only, jarvis_enabled

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def submit_execution_task(
    *,
    objective: str,
    priority: str = "normal",
    approval_mode: str = "auto",
    dry_run: bool = True,
) -> dict[str, Any]:
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")

    if jarvis_dry_run_only() and not dry_run:
        raise RuntimeError("Non-dry-run blocked while JARVIS_DRY_RUN_ONLY=true")

    task_id = str(uuid.uuid4())
    objective_text = (objective or "").strip()
    create_execution_task(
        task_id=task_id,
        objective=objective_text,
        priority=priority,
        dry_run=dry_run,
    )

    log_execution_event(
        task_id=task_id,
        agent="service",
        tool="submit",
        input_summary=objective_text[:500],
        output_summary="task queued",
        duration_ms=0,
    )

    transition_task_status(task_id, TaskLifecycleState.PLANNING, started_at=_now_iso())
    plan = build_plan(objective_text)
    plan_dict = plan_to_dict(plan)
    log_execution_event(
        task_id=task_id,
        agent="planner_agent",
        tool="build_plan",
        input_summary=objective_text[:500],
        output_summary=f"steps={len(plan.steps)} safety={plan.overall_safety}",
        duration_ms=0,
    )

    if is_forbidden(SafetyLevel(plan.overall_safety)):
        _update_task(
            task_id,
            status=TaskLifecycleState.FAILED.value,
            plan_json=plan_dict,
            error="Objective or plan classified as FORBIDDEN",
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    approval_required = plan.overall_safety == SafetyLevel.NEEDS_APPROVAL.value
    if approval_mode == "manual":
        approval_required = True

    approval_status = "pending" if approval_required else "not_required"
    _update_task(
        task_id,
        plan_json=plan_dict,
        estimated_cost_usd=plan.total_estimated_cost_usd,
        approval_required=approval_required,
        approval_status=approval_status,
    )

    if approval_required:
        transition_task_status(task_id, TaskLifecycleState.WAITING_FOR_APPROVAL)
        repo_artifact = create_artifact(
            task_id=task_id,
            name="plan_preview",
            content=plan_dict,
            fmt="json",
            metadata={"phase": "planning"},
        )
        _update_task(task_id, artifacts_json=[repo_artifact])
        return _detail(task_id)

    return _run_execution(task_id, plan)


def approve_task(task_id: str, *, actor_id: str = "dashboard", comment: str = "") -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    if row["status"] != TaskLifecycleState.WAITING_FOR_APPROVAL.value:
        raise ValueError(f"task not awaiting approval (status={row['status']})")

    record_approval(task_id=task_id, decision="approved", actor_id=actor_id, comment=comment)
    _update_task(task_id, approval_status="approved")
    transition_task_status(task_id, TaskLifecycleState.EXECUTING)

    plan = JarvisExecutionPlan.model_validate(row.get("plan") or {})
    return _run_execution(task_id, plan, already_executing=True)


def reject_task(task_id: str, *, actor_id: str = "dashboard", comment: str = "") -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    if row["status"] != TaskLifecycleState.WAITING_FOR_APPROVAL.value:
        raise ValueError(f"task not awaiting approval (status={row['status']})")

    record_approval(task_id=task_id, decision="rejected", actor_id=actor_id, comment=comment)
    transition_task_status(
        task_id,
        TaskLifecycleState.CANCELLED,
        approval_status="rejected",
        final_answer="Task rejected by approver.",
        completed_at=_now_iso(),
    )
    return _detail(task_id)


def _run_execution(task_id: str, plan: JarvisExecutionPlan, *, already_executing: bool = False) -> dict[str, Any]:
    if not already_executing:
        transition_task_status(task_id, TaskLifecycleState.EXECUTING)

    repo_result = investigate_objective(plan.objective_summary)
    repo_artifact = create_artifact(
        task_id=task_id,
        name="repository_investigation",
        content=repo_result,
        fmt="json",
        metadata={"agent": "repository_agent"},
    )
    log_execution_event(
        task_id=task_id,
        agent="repository_agent",
        tool="investigate_objective",
        input_summary=plan.objective_summary[:300],
        output_summary=f"queries={len(repo_result.get('queries', []))}",
        duration_ms=0,
    )

    exec_result = execute_plan(task_id=task_id, plan=plan)
    artifacts = [repo_artifact, *exec_result.get("artifacts", [])]

    if not exec_result.get("ok"):
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            tool_results_json=exec_result.get("tool_results", []),
            artifacts_json=artifacts,
            actual_cost_usd=exec_result.get("actual_cost_usd", 0.0),
            error=exec_result.get("error"),
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    transition_task_status(
        task_id,
        TaskLifecycleState.COMPLETED,
        tool_results_json=exec_result.get("tool_results", []),
        artifacts_json=artifacts,
        actual_cost_usd=exec_result.get("actual_cost_usd", 0.0),
        final_answer=exec_result.get("final_answer", ""),
        completed_at=_now_iso(),
    )
    return _detail(task_id)


def _detail(task_id: str) -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    row["execution_log"] = list_execution_log(task_id)
    row["approvals"] = list_approvals(task_id)
    return row


def get_execution_task_detail(task_id: str) -> dict[str, Any]:
    return _detail(task_id)
