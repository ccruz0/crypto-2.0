"""Tests for shared Jarvis tool kwargs builder."""

from __future__ import annotations

from app.jarvis.execution_tools.tool_invocation import build_tool_kwargs


class TestBuildToolKwargs:
    def test_inspect_health_does_not_receive_action(self):
        kwargs = build_tool_kwargs("inspect_health", objective="test", action="inspect_health")
        assert "action" not in kwargs
        assert "objective" not in kwargs

    def test_inspect_repository_does_not_receive_action(self):
        kwargs = build_tool_kwargs("inspect_repository", objective="test", action="inspect_repository")
        assert kwargs == {}

    def test_diagnose_open_orders_receives_objective_and_action(self):
        kwargs = build_tool_kwargs(
            "diagnose_open_orders",
            objective="Why are open orders empty?",
            action="diagnose_open_orders",
        )
        assert kwargs["objective"] == "Why are open orders empty?"
        assert kwargs["action"] == "diagnose_open_orders"

    def test_search_logs_keywords_from_params(self):
        kwargs = build_tool_kwargs(
            "search_logs",
            objective="x",
            action="search_logs",
            params={"keywords": ("open orders", "sync")},
        )
        assert kwargs["keywords"] == ("open orders", "sync")

    def test_query_database_preset_from_params(self):
        kwargs = build_tool_kwargs(
            "query_database",
            params={"preset": "count_open_orders"},
        )
        assert kwargs["preset"] == "count_open_orders"
