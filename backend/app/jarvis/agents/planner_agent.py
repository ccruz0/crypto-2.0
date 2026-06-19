"""Deterministic planner agent for Jarvis task execution."""

from __future__ import annotations

import re
from typing import Any

from app.jarvis.execution.cost_guard import CostGuard
from app.jarvis.execution.safety import SafetyLevel, classify_action, classify_text, merge_safety_levels
from app.jarvis.execution.schemas import JarvisExecutionPlan, JarvisExecutionStep
from app.jarvis.investigations.objective_classification import (
    InvestigationObjectiveType,
    classify_investigation_objective,
    get_plan_template,
)

_STEP_COST_USD = 0.02

# Legacy fine-grained patterns for numeric / narrow objectives (checked before type templates).
_LEGACY_SPECIFIC_PATTERNS: list[tuple[re.Pattern[str], list[tuple[str, str, str]]]] = [
    (
        re.compile(r"count.*open\s+orders|how\s+many.*open\s+orders|number\s+of\s+open\s+orders", re.IGNORECASE),
        [
            ("step_1", "count_open_orders", "query_database"),
            ("step_2", "search_repository", "search_repository"),
        ],
    ),
    (
        re.compile(r"position|trade\s+history", re.IGNORECASE),
        [
            ("step_1", "query_positions", "query_database"),
            ("step_2", "search_repository", "search_repository"),
            ("step_3", "search_logs", "search_logs"),
        ],
    ),
]


def _select_template(objective: str, investigation_type: InvestigationObjectiveType) -> list[tuple[str, str, str]]:
    for pattern, template in _LEGACY_SPECIFIC_PATTERNS:
        if pattern.search(objective):
            return template
    return [(step_id, action, tool) for step_id, action, tool, _desc in get_plan_template(investigation_type)]


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
            investigation_type=InvestigationObjectiveType.GENERIC_INVESTIGATION.value,
        )

    investigation_type = classify_investigation_objective(objective_text)
    template = _select_template(objective_text, investigation_type)
    steps: list[JarvisExecutionStep] = []
    safety_levels: list[SafetyLevel] = [objective_safety]

    descriptions = {
        step_id: desc
        for step_id, action, tool, desc in get_plan_template(investigation_type)
    }

    for step_id, action, tool in template:
        description = descriptions.get(step_id) or f"Execute {action} via {tool}"
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
        investigation_type=investigation_type.value,
    )


def plan_to_dict(plan: JarvisExecutionPlan) -> dict[str, Any]:
    return plan.model_dump()
