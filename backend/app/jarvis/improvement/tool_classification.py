"""Explicit tool categories for Jarvis improvement analytics."""

from __future__ import annotations

from typing import Literal

ToolCategory = Literal[
    "orchestration",
    "diagnostic",
    "collector",
    "validation",
    "reporting",
    "execution",
]

# Every tracked tool maps to exactly one category.
_TOOL_CATEGORIES: dict[str, ToolCategory] = {
    # Workflow orchestration — coordinate investigation lifecycle.
    "submit": "execution",
    "build_plan": "orchestration",
    "investigate_objective": "orchestration",
    "validate_result": "validation",
    # Evidence collectors — gather raw signals during investigations.
    "read_logs": "collector",
    "search_logs": "collector",
    "query_database": "collector",
    "search_repository": "collector",
    "inspect_container": "collector",
    "inspect_repository": "collector",
    "inspect_runtime": "collector",
    "inspect_health": "collector",
    # Diagnostic — produce structured diagnostic findings.
    "diagnose_open_orders": "diagnostic",
    "reconcile_crypto_com_open_orders": "diagnostic",
    # Reporting — summarize or present outcomes.
    "inspect_costs": "reporting",
}

# Tools that are mandatory workflow components but may also appear as collectors.
_WORKFLOW_PROTECTED_TOOLS: frozenset[str] = frozenset(
    {"read_logs", "submit", "build_plan", "investigate_objective", "validate_result"}
)

# Categories measured by workflow participation, not utility ratio.
_WORKFLOW_MEASURED_CATEGORIES: frozenset[ToolCategory] = frozenset(
    {"orchestration", "validation", "execution"}
)

# Categories measured by utility ratio and diagnostic contribution.
_DIAGNOSTIC_MEASURED_CATEGORIES: frozenset[ToolCategory] = frozenset(
    {"diagnostic", "collector", "reporting"}
)

_ASSESSMENT_DISPLAY: dict[ToolCategory, str] = {
    "orchestration": "Workflow Tool",
    "execution": "Workflow Tool",
    "validation": "Validation Tool",
    "diagnostic": "Diagnostic Tool",
    "collector": "Collector",
    "reporting": "Reporting Tool",
}

_DEPRECATION_PHRASES: tuple[str, ...] = (
    "remove tool",
    "lower priority",
    "reduce usage",
    "remove from",
    "lower priority or remove",
)


def classify_tool(tool: str) -> ToolCategory:
    """Return the category for a tool; unknown tools default to diagnostic."""
    return _TOOL_CATEGORIES.get(str(tool), "diagnostic")


def is_workflow_protected_tool(tool: str) -> bool:
    """Mandatory workflow components that must not receive deprecation recommendations."""
    return str(tool) in _WORKFLOW_PROTECTED_TOOLS


def is_workflow_measured_tool(tool: str) -> bool:
    """True when tool effectiveness uses workflow metrics instead of utility ratio."""
    return classify_tool(tool) in _WORKFLOW_MEASURED_CATEGORIES


def is_diagnostic_measured_tool(tool: str) -> bool:
    return classify_tool(tool) in _DIAGNOSTIC_MEASURED_CATEGORIES


def get_assessment_display(category: ToolCategory) -> str:
    return _ASSESSMENT_DISPLAY.get(category, "Diagnostic Tool")


def all_known_tools() -> tuple[str, ...]:
    return tuple(sorted(_TOOL_CATEGORIES.keys()))


def is_deprecation_recommendation(recommendation_text: str) -> bool:
    """Detect remove/lower-priority style recommendations."""
    lowered = str(recommendation_text or "").lower()
    return any(phrase in lowered for phrase in _DEPRECATION_PHRASES)


def extract_tool_from_recommendation_id(rec_id: str) -> str | None:
    """Extract tool name from tool-effectiveness recommendation ids."""
    prefix = "tool-low-utility-"
    if rec_id.startswith(prefix):
        return rec_id[len(prefix) :]
    prefix = "tool-low-success-"
    if rec_id.startswith(prefix):
        return rec_id[len(prefix) :]
    prefix = "tool-slow-"
    if rec_id.startswith(prefix):
        return rec_id[len(prefix) :]
    prefix = "tool-failure-"
    if rec_id.startswith(prefix):
        return rec_id[len(prefix) :]
    return None


def should_suppress_workflow_recommendation(rec: dict) -> bool:
    """Suppress deprecation-style recommendations for workflow-measured or protected tools."""
    if rec.get("category") != "tool_effectiveness":
        return False
    tool = extract_tool_from_recommendation_id(str(rec.get("id") or ""))
    if tool is None:
        return False
    if not (is_workflow_measured_tool(tool) or is_workflow_protected_tool(tool)):
        return False
    text = f"{rec.get('recommendation', '')} {rec.get('title', '')}"
    return is_deprecation_recommendation(text)
