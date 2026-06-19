"""Shared keyword-argument builder for Jarvis read-only diagnostic tools."""

from __future__ import annotations

from typing import Any

# Tools that accept objective/action for planner-style routing.
_TOOLS_WITH_OBJECTIVE_ACTION = frozenset(
    {
        "diagnose_open_orders",
        "reconcile_crypto_com_open_orders",
        "search_logs",
        "search_repository",
        "query_database",
        "read_logs",
    }
)


def build_tool_kwargs(
    tool: str,
    *,
    objective: str = "",
    action: str = "",
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Build handler kwargs for a registered tool.

    Only passes parameters each tool's signature accepts — never blanket action/objective.
    """
    kwargs: dict[str, Any] = {}
    extra = params or {}

    if tool in _TOOLS_WITH_OBJECTIVE_ACTION:
        if objective:
            kwargs["objective"] = objective
        if action:
            kwargs["action"] = action

    if tool == "search_logs":
        keywords = extra.get("keywords")
        if keywords:
            kwargs["keywords"] = keywords
        keyword = extra.get("keyword")
        if keyword and "keywords" not in kwargs:
            kwargs["keyword"] = keyword

    if tool == "search_repository" and extra.get("topic"):
        kwargs["topic"] = extra["topic"]
    elif tool == "search_repository" and action == "inspect_exchange_sync_mapping_readonly":
        kwargs["topic"] = "exchange_sync"

    if tool == "search_logs" and action == "inspect_relevant_logs_readonly":
        kwargs["keywords"] = kwargs.get("keywords") or (
            "open orders",
            "sync",
            "exchange_sync",
            "reconcile",
            "50001",
            "trigger",
        )

    if tool == "query_database":
        if extra.get("preset"):
            kwargs["preset"] = extra["preset"]
        if extra.get("query"):
            kwargs["query"] = extra["query"]
        if extra.get("limit") is not None:
            kwargs["limit"] = extra["limit"]

    if tool == "inspect_health" and extra.get("endpoint"):
        kwargs["endpoint"] = extra["endpoint"]

    if tool == "inspect_repository" and extra.get("path"):
        kwargs["path"] = extra["path"]

    if tool == "inspect_container" and extra.get("service"):
        kwargs["service"] = extra["service"]

    return kwargs


__all__ = ["build_tool_kwargs"]
