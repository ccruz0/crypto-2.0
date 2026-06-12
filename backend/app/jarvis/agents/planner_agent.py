"""Deterministic planner agent for Jarvis task execution."""

from __future__ import annotations

import re
from typing import Any

from app.jarvis.execution.cost_guard import CostGuard
from app.jarvis.execution.safety import SafetyLevel, classify_action, classify_text, merge_safety_levels
from app.jarvis.execution.schemas import JarvisExecutionPlan, JarvisExecutionStep

_STEP_COST_USD = 0.02

# Ordered objective patterns -> plan template (deterministic).
_PLAN_TEMPLATES: list[tuple[re.Pattern[str], list[tuple[str, str, str]]]] = [
    (
        re.compile(r"deploy|deployment|health", re.IGNORECASE),
        [
            ("step_1", "gather_logs", "read_logs", "Gather recent deployment/application logs"),
            ("step_2", "inspect_health", "inspect_health", "Inspect dashboard and API health"),
            ("step_3", "inspect_runtime", "inspect_runtime", "Inspect runtime environment flags"),
            ("step_4", "recommend_fix", "inspect_repository", "Review repository state for drift"),
        ],
    ),
    (
        re.compile(r"websocket|ws", re.IGNORECASE),
        [
            ("step_1", "search_repository", "inspect_repository", "Inspect repository layout"),
            ("step_2", "inspect_code", "inspect_repository", "Locate websocket-related modules"),
            ("step_3", "summarize_architecture", "inspect_runtime", "Summarize runtime websocket configuration"),
        ],
    ),
    (
        re.compile(r"jarvis|architecture", re.IGNORECASE),
        [
            ("step_1", "inspect_repository", "inspect_repository", "Map Jarvis modules in repository"),
            ("step_2", "summarize_modules", "inspect_runtime", "Summarize Jarvis runtime configuration"),
            ("step_3", "inspect_health", "inspect_health", "Verify Jarvis/API health endpoints"),
        ],
    ),
    (
        re.compile(r"openclaw", re.IGNORECASE),
        [
            ("step_1", "search_repository", "inspect_repository", "Search repository for OpenClaw references"),
            ("step_2", "inspect_runtime", "inspect_runtime", "Inspect runtime OpenClaw-related flags"),
            ("step_3", "inspect_health", "inspect_health", "Verify public route health expectations"),
        ],
    ),
    (
        re.compile(r"container|docker|running", re.IGNORECASE),
        [
            ("step_1", "inspect_container", "inspect_container", "Inspect running containers"),
            ("step_2", "inspect_runtime", "inspect_runtime", "Inspect runtime service configuration"),
            ("step_3", "inspect_health", "inspect_health", "Verify service health endpoints"),
        ],
    ),
]

_DEFAULT_TEMPLATE: list[tuple[str, str, str]] = [
    ("step_1", "gather_logs", "read_logs", "Gather contextual logs"),
    ("step_2", "inspect_health", "inspect_health", "Inspect system health"),
    ("step_3", "identify_root_cause", "inspect_repository", "Review repository and runtime context"),
]


def _select_template(objective: str) -> list[tuple[str, str, str]]:
    for pattern, template in _PLAN_TEMPLATES:
        if pattern.search(objective):
            return template
    return _DEFAULT_TEMPLATE


def build_plan(objective: str) -> JarvisExecutionPlan:
    """Build a deterministic, schema-valid plan for the given objective."""
    objective_text = (objective or "").strip()
    objective_safety = classify_text(objective_text)
    if objective_safety == SafetyLevel.FORBIDDEN:
        return JarvisExecutionPlan(
            steps=[],
            total_estimated_cost_usd=0.0,
            overall_safety=SafetyLevel.FORBIDDEN.value,
            objective_summary=objective_text,
        )

    template = _select_template(objective_text)
    steps: list[JarvisExecutionStep] = []
    safety_levels: list[SafetyLevel] = [objective_safety]

    for step_id, action, tool, description in template:
        step_safety = merge_safety_levels(classify_action(action), classify_action(tool))
        safety_levels.append(step_safety)
        steps.append(
            JarvisExecutionStep(
                id=step_id,
                action=action,
                tool=tool,
                description=description,
                safety_level=step_safety.value,
                estimated_cost_usd=_STEP_COST_USD,
            )
        )

    total = round(len(steps) * _STEP_COST_USD, 4)
    guard = CostGuard()
    guard.check_estimated_cost(total)

    overall = merge_safety_levels(*safety_levels)
    return JarvisExecutionPlan(
        steps=steps,
        total_estimated_cost_usd=total,
        overall_safety=overall.value,
        objective_summary=objective_text[:500],
    )


def plan_to_dict(plan: JarvisExecutionPlan) -> dict[str, Any]:
    return plan.model_dump()
