"""Read-only executor agent for Jarvis task steps."""

from __future__ import annotations

import time
from typing import Any

from app.jarvis.artifacts.storage import create_artifact
from app.jarvis.execution.audit import log_execution_event
from app.jarvis.execution.cost_guard import CostGuard, CostGuardViolation
from app.jarvis.execution.schemas import JarvisExecutionPlan, JarvisExecutionStep
from app.jarvis.execution_tools.registry import ToolRegistry, build_default_registry


def execute_plan(
    *,
    task_id: str,
    plan: JarvisExecutionPlan | dict[str, Any],
    registry: ToolRegistry | None = None,
    cost_guard: CostGuard | None = None,
) -> dict[str, Any]:
    """Execute approved read-only plan steps and collect artifacts."""
    reg = registry or build_default_registry()
    guard = cost_guard or CostGuard()
    if isinstance(plan, dict):
        plan_obj = JarvisExecutionPlan.model_validate(plan)
    else:
        plan_obj = plan

    started = time.perf_counter()
    tool_results: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    current_step: str | None = None
    final_parts: list[str] = []

    for step in plan_obj.steps:
        current_step = step.id
        signature = f"{step.tool}:{step.action}"
        try:
            guard.begin_step(signature, step_cost_usd=step.estimated_cost_usd)
        except CostGuardViolation as exc:
            return _failure(task_id, str(exc), tool_results, artifacts, current_step, guard)

        result = reg.execute(step.tool, action=step.action, objective=plan_obj.objective_summary)
        tool_results.append(
            {
                "step_id": step.id,
                "action": step.action,
                "tool": step.tool,
                "ok": result.ok,
                "output": result.output,
                "error": result.error,
                "duration_ms": result.duration_ms,
            }
        )

        summary = result.output.get("status") if result.ok else (result.error or "failed")
        log_execution_event(
            task_id=task_id,
            agent="executor_agent",
            tool=step.tool,
            input_summary=f"{step.action}: {step.description}",
            output_summary=str(summary)[:500],
            duration_ms=result.duration_ms,
            metadata={"step_id": step.id, "read_only": True},
        )

        artifact = create_artifact(
            task_id=task_id,
            name=f"{step.action}_output",
            content=result.output if result.ok else {"error": result.error},
            fmt="json",
            step_id=step.id,
            metadata={"tool": step.tool, "action": step.action},
        )
        artifacts.append(artifact)
        final_parts.append(f"{step.action}: {summary}")

    guard.check_duration(time.perf_counter() - started)
    return {
        "ok": True,
        "tool_results": tool_results,
        "artifacts": artifacts,
        "current_step": None,
        "final_answer": "\n".join(final_parts),
        "actual_cost_usd": guard.state.actual_cost_usd,
        "step_count": guard.state.step_count,
    }


def _failure(
    task_id: str,
    error: str,
    tool_results: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    current_step: str | None,
    guard: CostGuard,
) -> dict[str, Any]:
    log_execution_event(
        task_id=task_id,
        agent="executor_agent",
        tool="cost_guard",
        input_summary="execution aborted",
        output_summary=error[:500],
        duration_ms=0,
    )
    return {
        "ok": False,
        "error": error,
        "tool_results": tool_results,
        "artifacts": artifacts,
        "current_step": current_step,
        "final_answer": "",
        "actual_cost_usd": guard.state.actual_cost_usd,
        "step_count": guard.state.step_count,
    }
