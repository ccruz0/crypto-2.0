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
        re.compile(
            r"why\s+are\s+open\s+orders\s+empty|why\s+does\s+dashboard\s+differ|"
            r"portfolio\s+value\s+incorrect|websocket\s+prices?\s+stale|"
            r"jarvis\s+task\s+failing|deployment\s+unhealthy|exchange\s+auth\s+fail|"
            r"dashboard\s+showing\s+stale|crypto\.?com\s+auth\s+fail",
            re.IGNORECASE,
        ),
        [
            ("step_1", "run_investigation", "diagnose_open_orders", "Collect multi-source production evidence"),
            ("step_2", "reconcile_exchange", "reconcile_crypto_com_open_orders", "Reconcile exchange vs DB vs dashboard"),
            ("step_3", "search_logs", "search_logs", "Search logs for sync and API errors"),
            ("step_4", "search_repository", "search_repository", "Locate related code and configuration"),
        ],
    ),
    (
        re.compile(r"count.*open\s+orders|how\s+many.*open\s+orders|number\s+of\s+open\s+orders", re.IGNORECASE),
        [
            ("step_1", "count_open_orders", "query_database", "Count open orders in exchange_orders table"),
            ("step_2", "search_repository", "search_repository", "Locate open orders API route and frontend hook"),
        ],
    ),
    (
        re.compile(r"diagnos.*open\s+orders|open\s+orders.*end[\s-]to[\s-]end", re.IGNORECASE),
        [
            ("step_1", "diagnose_open_orders", "diagnose_open_orders", "Run end-to-end open orders diagnostic"),
            ("step_2", "search_repository", "search_repository", "Find open orders API and frontend code"),
            ("step_3", "search_logs", "search_logs", "Search logs for order sync and API errors"),
        ],
    ),
    (
        re.compile(r"open\s+orders|why.*empty.*order|empty.*open\s+order", re.IGNORECASE),
        [
            ("step_1", "diagnose_open_orders", "diagnose_open_orders", "Diagnose open orders DB vs cache vs API"),
            ("step_2", "search_repository", "search_repository", "Find open orders frontend and API mapping"),
            ("step_3", "search_logs", "search_logs", "Search backend logs for open orders issues"),
        ],
    ),
    (
        re.compile(r"position|trade\s+history", re.IGNORECASE),
        [
            ("step_1", "query_positions", "query_database", "Inspect open positions from exchange_orders"),
            ("step_2", "search_repository", "search_repository", "Find positions and trade history code"),
            ("step_3", "search_logs", "search_logs", "Search logs for position/trade events"),
        ],
    ),
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
