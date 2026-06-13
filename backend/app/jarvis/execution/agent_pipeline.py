"""Derive multi-agent operational status from Jarvis task execution data."""

from __future__ import annotations

from typing import Any, Literal

from app.jarvis.execution.lifecycle import TaskLifecycleState

AgentStatus = Literal["idle", "pending", "running", "completed", "failed", "skipped"]

AGENT_ORDER: tuple[str, ...] = (
    "supervisor",
    "planner",
    "repository",
    "patch",
    "reviewer",
    "test",
    "cost_guard",
)

AGENT_LABELS: dict[str, str] = {
    "supervisor": "Supervisor",
    "planner": "Planner",
    "repository": "Repository Agent",
    "patch": "Patch Agent",
    "reviewer": "Reviewer",
    "test": "Test Agent",
    "cost_guard": "Cost Guard",
}

# Log `agent` field values mapped to panel agent ids.
LOG_AGENT_MAP: dict[str, str] = {
    "supervisor": "supervisor",
    "service": "supervisor",
    "planner": "planner",
    "planner_agent": "planner",
    "repository_agent": "repository",
    "patch_agent": "patch",
    "reviewer_agent": "reviewer",
    "reviewer": "reviewer",
    "test_agent": "test",
    "executor_agent": "test",
    "cost_guard": "cost_guard",
}

# Task lifecycle status → active agent id.
STATUS_ACTIVE_AGENT: dict[str, str] = {
    TaskLifecycleState.QUEUED.value: "supervisor",
    TaskLifecycleState.PLANNING.value: "planner",
    TaskLifecycleState.INVESTIGATING.value: "repository",
    TaskLifecycleState.PATCH_READY.value: "patch",
    TaskLifecycleState.REVIEWING.value: "reviewer",
    TaskLifecycleState.TESTING.value: "test",
    TaskLifecycleState.EXECUTING.value: "test",
}

# Phase 3 investigation skips patch/reviewer; Phase 4 change uses full pipeline.
PHASE3_SKIP: frozenset[str] = frozenset({"patch", "reviewer"})
PHASE4_SKIP: frozenset[str] = frozenset()


def _workflow_type(plan: dict[str, Any] | None) -> str:
    if not plan:
        return "phase3_investigation"
    wt = plan.get("workflow_type")
    if wt == "phase4_change":
        return "phase4_change"
    return "phase3_investigation"


def _skipped_agents(workflow: str) -> frozenset[str]:
    return PHASE4_SKIP if workflow == "phase4_change" else PHASE3_SKIP


def _normalize_status(raw: str | None) -> str:
    return (raw or "queued").strip().lower()


def _is_terminal(status: str) -> bool:
    return status in {
        TaskLifecycleState.COMPLETED.value,
        TaskLifecycleState.FAILED.value,
        TaskLifecycleState.CANCELLED.value,
    }


def _logs_for_agent(logs: list[dict[str, Any]], agent_id: str) -> list[dict[str, Any]]:
    matched: list[dict[str, Any]] = []
    for entry in logs:
        mapped = LOG_AGENT_MAP.get(str(entry.get("agent", "")).lower())
        if mapped == agent_id:
            matched.append(entry)
        elif agent_id == "cost_guard" and str(entry.get("tool", "")).lower() == "cost_guard":
            matched.append(entry)
        elif agent_id == "supervisor" and str(entry.get("agent", "")).lower() == "service":
            matched.append(entry)
    return matched


def _last_action(logs: list[dict[str, Any]]) -> str | None:
    if not logs:
        return None
    last = logs[-1]
    tool = last.get("tool") or ""
    summary = last.get("output_summary") or last.get("input_summary") or ""
    if tool:
        return f"{tool}: {summary}"[:240]
    return str(summary)[:240] if summary else None


def _total_duration_ms(logs: list[dict[str, Any]]) -> int:
    return sum(int(entry.get("duration_ms") or 0) for entry in logs)


def _agent_errors(logs: list[dict[str, Any]], task_error: str | None) -> list[str]:
    errors: list[str] = []
    for entry in logs:
        meta = entry.get("metadata") or {}
        if meta.get("error"):
            errors.append(str(meta["error"])[:500])
        summary = str(entry.get("output_summary") or "")
        if summary.upper().startswith(("ERROR", "FAILED", "FORBIDDEN")):
            errors.append(summary[:500])
    if task_error and logs:
        errors.append(task_error[:500])
    return errors


def _estimate_cost_for_agent(agent_id: str, plan: dict[str, Any], total_estimated: float) -> float:
    steps = plan.get("steps") or []
    if not steps:
        # Spread evenly across active agents when no step breakdown exists.
        active_count = len(AGENT_ORDER) - len(PHASE3_SKIP)
        share = total_estimated / max(active_count, 1)
        if agent_id in PHASE3_SKIP:
            return 0.0
        return round(share, 6)

    if agent_id == "planner":
        return round(_STEP_COST * 1, 6)
    if agent_id == "repository":
        return round(_STEP_COST * 0.5, 6)
    if agent_id == "test":
        step_cost = sum(float(s.get("estimated_cost_usd") or 0) for s in steps)
        return round(step_cost, 6)
    if agent_id == "cost_guard":
        return 0.0
    if agent_id in {"patch", "reviewer"}:
        return round(_STEP_COST * 2, 6)
    return round(_STEP_COST * 0.25, 6)


_STEP_COST = 0.02


def _actual_cost_for_agent(
    agent_id: str,
    agent_logs: list[dict[str, Any]],
    total_actual: float,
    *,
    has_activity: bool,
) -> float:
    meta_cost = sum(float((entry.get("metadata") or {}).get("cost_usd") or 0) for entry in agent_logs)
    if meta_cost > 0:
        return round(meta_cost, 6)
    if not has_activity or total_actual <= 0:
        return 0.0
    # Fallback: attribute executor step costs to test agent; flat slice for others.
    if agent_id == "test" and agent_logs:
        return round(total_actual, 6)
    if agent_logs:
        return round(total_actual * 0.1, 6)
    return 0.0


def build_agent_pipeline(task: dict[str, Any]) -> dict[str, Any]:
    """Build operational panel payload for a Jarvis execution task."""
    if not task.get("task_id"):
        return {
            "task_id": None,
            "workflow_type": "phase3_investigation",
            "task_status": "idle",
            "agents": [
                {
                    "id": agent_id,
                    "label": AGENT_LABELS[agent_id],
                    "status": "idle",
                    "last_action": None,
                    "estimated_cost_usd": 0.0,
                    "actual_cost_usd": 0.0,
                    "duration_ms": 0,
                    "errors": [],
                    "logs": [],
                }
                for agent_id in AGENT_ORDER
            ],
            "totals": {"estimated_cost_usd": 0.0, "actual_cost_usd": 0.0},
        }

    status = _normalize_status(task.get("status"))
    plan = task.get("plan") or {}
    if not isinstance(plan, dict):
        plan = {}
    workflow = _workflow_type(plan)
    skipped = _skipped_agents(workflow)
    logs = list(task.get("execution_log") or [])
    task_error = task.get("error")
    total_estimated = float(task.get("estimated_cost_usd") or plan.get("total_estimated_cost_usd") or 0)
    total_actual = float(task.get("actual_cost_usd") or 0)
    active_agent = STATUS_ACTIVE_AGENT.get(status)
    terminal = _is_terminal(status)
    failed = status == TaskLifecycleState.FAILED.value

    agents_out: list[dict[str, Any]] = []
    reached_running = False

    for agent_id in AGENT_ORDER:
        label = AGENT_LABELS[agent_id]
        if agent_id in skipped:
            agents_out.append(
                {
                    "id": agent_id,
                    "label": label,
                    "status": "skipped",
                    "last_action": None,
                    "estimated_cost_usd": 0.0,
                    "actual_cost_usd": 0.0,
                    "duration_ms": 0,
                    "errors": [],
                    "logs": [],
                }
            )
            continue

        agent_logs = _logs_for_agent(logs, agent_id)
        has_activity = bool(agent_logs) or (
            agent_id == "planner" and bool(plan.get("steps"))
        )

        if failed and active_agent == agent_id:
            agent_status: AgentStatus = "failed"
        elif terminal and has_activity:
            agent_status = "failed" if _agent_errors(agent_logs, None) and agent_id == active_agent else "completed"
        elif active_agent == agent_id and not terminal:
            agent_status = "running"
            reached_running = True
        elif has_activity:
            agent_status = "completed"
        elif reached_running or (active_agent and AGENT_ORDER.index(agent_id) < AGENT_ORDER.index(active_agent)):
            agent_status = "pending"
        elif status == TaskLifecycleState.WAITING_FOR_APPROVAL.value and has_activity:
            agent_status = "completed"
        elif status == TaskLifecycleState.WAITING_FOR_APPROVAL.value:
            agent_status = "pending"
        else:
            agent_status = "idle" if not task.get("task_id") else "pending"

        # Cost guard runs at end of pipeline.
        if agent_id == "cost_guard":
            if status in {TaskLifecycleState.COMPLETED.value, TaskLifecycleState.FAILED.value}:
                agent_status = "failed" if failed and any(
                    str(e.get("tool", "")).lower() == "cost_guard" for e in agent_logs
                ) else ("completed" if has_activity or terminal else agent_status)
            elif terminal:
                agent_status = "completed"

        if agent_id == "supervisor" and status in {
            TaskLifecycleState.PLANNING.value,
            TaskLifecycleState.WAITING_FOR_APPROVAL.value,
            TaskLifecycleState.EXECUTING.value,
            TaskLifecycleState.INVESTIGATING.value,
        }:
            if agent_logs:
                agent_status = "completed"

        if agent_id == "planner" and plan.get("steps") and status not in {
            TaskLifecycleState.QUEUED.value,
            TaskLifecycleState.PLANNING.value,
        }:
            agent_status = "completed" if agent_status != "running" else agent_status

        errors = _agent_errors(agent_logs, task_error if agent_status == "failed" else None)

        agents_out.append(
            {
                "id": agent_id,
                "label": label,
                "status": agent_status,
                "last_action": _last_action(agent_logs),
                "estimated_cost_usd": _estimate_cost_for_agent(agent_id, plan, total_estimated),
                "actual_cost_usd": _actual_cost_for_agent(
                    agent_id, agent_logs, total_actual, has_activity=has_activity
                ),
                "duration_ms": _total_duration_ms(agent_logs),
                "errors": errors,
                "logs": [
                    {
                        "log_id": entry.get("log_id"),
                        "timestamp": entry.get("timestamp"),
                        "tool": entry.get("tool"),
                        "input_summary": entry.get("input_summary"),
                        "output_summary": entry.get("output_summary"),
                        "duration_ms": entry.get("duration_ms"),
                    }
                    for entry in agent_logs
                ],
            }
        )

    return {
        "task_id": task.get("task_id"),
        "workflow_type": workflow,
        "task_status": status,
        "agents": agents_out,
        "totals": {
            "estimated_cost_usd": total_estimated,
            "actual_cost_usd": total_actual,
        },
    }
