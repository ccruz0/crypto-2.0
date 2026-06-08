"""LangGraph workflow for Jarvis LangGraph MVP."""

from __future__ import annotations

import logging
from typing import Any, Literal, TypedDict

from langgraph.graph import END, StateGraph

from app.jarvis.mvp.agents import (
    aws_auditor_agent,
    cost_guard_agent,
    crypto_auditor_agent,
    executor_agent,
    planner_agent,
    reviewer_agent,
    supervisor_agent,
)
from app.jarvis.mvp.aws_auditor import is_aws_audit_task
from app.jarvis.mvp.crypto_auditor import is_crypto_audit_task

logger = logging.getLogger(__name__)


class JarvisTaskState(TypedDict, total=False):
    task_id: str
    task: str
    dry_run: bool
    status: str
    risk_level: str
    plan: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    review: dict[str, Any]
    estimated_cost_usd: float
    final_answer: str
    model_calls: int
    tool_calls: int
    audit_output: dict[str, Any]
    crypto_audit_output: dict[str, Any]


def _route_after_supervisor(state: JarvisTaskState) -> Literal["planner", "cost_guard"]:
    if str(state.get("risk_level")) == "high":
        return "cost_guard"
    return "planner"


def _route_after_planner(
    state: JarvisTaskState,
) -> Literal["aws_auditor", "crypto_auditor", "executor"]:
    task = str(state.get("task") or "")
    if is_aws_audit_task(task):
        return "aws_auditor"
    if is_crypto_audit_task(task):
        return "crypto_auditor"
    return "executor"


def build_jarvis_graph():
    """Compile the Jarvis multi-agent LangGraph."""
    workflow: StateGraph = StateGraph(JarvisTaskState)
    workflow.add_node("supervisor", supervisor_agent)
    workflow.add_node("planner", planner_agent)
    workflow.add_node("aws_auditor", aws_auditor_agent)
    workflow.add_node("crypto_auditor", crypto_auditor_agent)
    workflow.add_node("executor", executor_agent)
    workflow.add_node("reviewer", reviewer_agent)
    workflow.add_node("cost_guard", cost_guard_agent)

    workflow.set_entry_point("supervisor")
    workflow.add_conditional_edges(
        "supervisor",
        _route_after_supervisor,
        {"planner": "planner", "cost_guard": "cost_guard"},
    )
    workflow.add_conditional_edges(
        "planner",
        _route_after_planner,
        {"aws_auditor": "aws_auditor", "crypto_auditor": "crypto_auditor", "executor": "executor"},
    )
    workflow.add_edge("aws_auditor", "reviewer")
    workflow.add_edge("crypto_auditor", "reviewer")
    workflow.add_edge("executor", "reviewer")
    workflow.add_edge("reviewer", "cost_guard")
    workflow.add_edge("cost_guard", END)

    return workflow.compile()


_GRAPH = None


def reset_jarvis_graph_cache() -> None:
    """Clear compiled graph cache (used in tests)."""
    global _GRAPH
    _GRAPH = None


def get_jarvis_graph():
    global _GRAPH
    if _GRAPH is None:
        _GRAPH = build_jarvis_graph()
        logger.info("jarvis.mvp.graph compiled")
    return _GRAPH
