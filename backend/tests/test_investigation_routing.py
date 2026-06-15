"""Tests for investigation template routing from natural-language objectives."""

from __future__ import annotations

import pytest

from app.jarvis.investigations.investigation_types import (
    get_collectors_for_objective,
    match_investigation_template,
)

_DASHBOARD_MISMATCH_PHRASES = (
    "Why are my open orders different from Crypto.com?",
    "not all my open orders are there",
    "missing trigger orders",
    "Crypto.com shows more orders than dashboard",
    "dashboard not matching exchange",
    "orders missing from Crypto.com",
    "Crypto.com shows more orders",
    "dashboard missing orders",
    "not all open orders are there",
    "trigger orders not showing",
    "open orders not matching",
    "Why does dashboard differ from exchange?",
    "Why was dashboard showing zero orders while exchange had one?",
)

_REQUIRED_COLLECTORS = frozenset({"reconcile_crypto_com_open_orders", "diagnose_open_orders"})
_OPTIONAL_COLLECTORS = frozenset({"query_database", "search_logs", "search_repository"})


class TestDashboardExchangeMismatchRouting:
    @pytest.mark.parametrize("objective", _DASHBOARD_MISMATCH_PHRASES)
    def test_phrase_selects_dashboard_exchange_mismatch_template(self, objective: str):
        template = match_investigation_template(objective)
        assert template is not None
        assert template.template_id == "dashboard_exchange_mismatch"
        assert template.category == "dashboard"

    @pytest.mark.parametrize("objective", _DASHBOARD_MISMATCH_PHRASES)
    def test_phrase_includes_reconcile_and_diagnose_collectors(self, objective: str):
        category, template_id, collectors = get_collectors_for_objective(objective)
        assert category == "dashboard"
        assert template_id == "dashboard_exchange_mismatch"
        tool_names = {c.tool for c in collectors}
        assert _REQUIRED_COLLECTORS <= tool_names
        assert tool_names & _OPTIONAL_COLLECTORS

    def test_open_orders_empty_still_wins_over_mismatch_phrasing(self):
        template = match_investigation_template("Why are open orders empty?")
        assert template is not None
        assert template.template_id == "open_orders_empty"

    def test_generic_orders_query_falls_back_without_mismatch_signal(self):
        category, template_id, collectors = get_collectors_for_objective(
            "How do open orders work in the API?"
        )
        assert template_id == "generic"
        assert category == "orders"
        tool_names = {c.tool for c in collectors}
        assert "reconcile_crypto_com_open_orders" not in tool_names
        assert "diagnose_open_orders" not in tool_names


class TestPortfolioEquityDerivedRouting:
    _OBJECTIVE = "Why is portfolio equity derived instead of exchange-reported?"

    def test_selects_portfolio_equity_derived_template(self):
        template = match_investigation_template(self._OBJECTIVE)
        assert template is not None
        assert template.template_id == "portfolio_equity_derived"

    def test_query_database_collector_includes_open_positions_preset(self):
        _, template_id, collectors = get_collectors_for_objective(self._OBJECTIVE)
        assert template_id == "portfolio_equity_derived"
        db_collectors = [c for c in collectors if c.tool == "query_database"]
        assert len(db_collectors) == 1
        assert db_collectors[0].params.get("preset") == "open_positions"
