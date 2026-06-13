"""Tests for open-order investigation accuracy and mandatory tool handling."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.jarvis.execution.result_validation import validate_task_result
from app.jarvis.execution_tools.registry import build_default_registry
from app.jarvis.investigations.investigation_report import rank_root_causes
from app.jarvis.investigations.investigation_runner import collect_evidence, run_investigation
from app.jarvis.investigations.investigation_types import InvestigationStatus


class TestInspectToolsAcceptLegacyKwargs:
    def test_inspect_health_accepts_action_kwarg(self):
        registry = build_default_registry()
        result = registry.execute("inspect_health", action="inspect_health", objective="test")
        assert result.ok is True
        assert result.error is None

    def test_inspect_repository_accepts_action_kwarg(self):
        registry = build_default_registry()
        result = registry.execute("inspect_repository", action="inspect_repository", objective="test")
        assert result.ok is True
        assert result.error is None


class TestDiagnoseOpenOrdersAccuracy:
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_live_exchange")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_dashboard_effective")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    @patch("app.jarvis.execution_tools.diagnose_open_orders.query_database")
    def test_db_fallback_not_reported_as_empty_dashboard(
        self, mock_query, mock_cache, mock_dashboard, mock_exchange
    ):
        def _query_side(*, preset=None, **kwargs):
            if preset == "count_open_orders":
                return {"ok": True, "count": 1, "numeric_result": 1, "query_executed": "SELECT COUNT(*)"}
            return {"ok": True, "rows": [], "status_counts": {}, "query_executed": "", "row_count": 0}

        mock_query.side_effect = _query_side
        mock_cache.return_value = (
            0,
            {"source": "api", "reference": "cache", "detail": "raw cache empty", "confidence": "high"},
        )
        mock_dashboard.return_value = (
            1,
            "database_fallback",
            "stale_cache_db_fallback",
            {
                "source": "dashboard",
                "reference": "resolve_open_orders",
                "detail": "effective=1 via database_fallback",
                "confidence": "high",
            },
        )
        mock_exchange.return_value = (
            {
                "regular_count": 1,
                "trigger_count": 0,
                "total_count": 1,
                "data_verified": True,
                "skipped": False,
                "trigger_orders_error": "400 Bad Request",
                "trigger_orders_error_code": None,
            },
            {
                "source": "exchange",
                "reference": "live",
                "detail": "live exchange regular=1",
                "confidence": "high",
            },
        )

        from app.jarvis.execution_tools.diagnose_open_orders import diagnose_open_orders

        result = diagnose_open_orders()
        assert "api cache returned 0" not in (result.get("conclusion") or "").lower()
        assert result["dashboard_effective_count"] == 1
        assert result["exchange_total_count"] == 1
        assert "fallback" in (result.get("root_cause") or "").lower()


class TestMandatoryToolFailures:
    @patch("app.jarvis.investigations.investigation_runner.build_default_registry")
    def test_mandatory_tool_failure_yields_partial_failure(self, mock_registry_factory):
        registry = MagicMock()

        def _execute(name, **kwargs):
            if name == "reconcile_crypto_com_open_orders":
                return MagicMock(ok=False, error="exchange API timeout", output={"tool": name, "ok": False})
            if name == "diagnose_open_orders":
                return MagicMock(
                    ok=True,
                    output={
                        "tool": "diagnose_open_orders",
                        "ok": True,
                        "root_cause": "Open orders cache empty but dashboard API serves database fallback",
                        "evidence": [
                            {
                                "source": "exchange",
                                "reference": "live",
                                "detail": "regular=1",
                                "confidence": "high",
                            }
                        ],
                    },
                )
            return MagicMock(ok=True, output={"tool": name, "ok": True})

        registry.execute.side_effect = _execute
        mock_registry_factory.return_value = registry

        report = run_investigation(
            "Why was dashboard showing zero orders while exchange had one?",
            persist=False,
        )
        assert report.status == InvestigationStatus.PARTIAL_FAILURE
        assert report.to_dict()["passed"] is False
        assert any("reconcile_crypto_com_open_orders" in f for f in report.collector_failures)


class TestResultValidationToolFailures:
    def test_failed_inspect_health_blocks_passed(self):
        result = validate_task_result(
            objective="Why are open orders empty?",
            task_type="investigation",
            tool_results=[
                {
                    "tool": "inspect_health",
                    "ok": False,
                    "error": "inspect_health() got an unexpected keyword argument 'action'",
                },
                {
                    "tool": "diagnose_open_orders",
                    "ok": True,
                    "output": {
                        "root_cause": "test",
                        "conclusion": "test conclusion",
                        "evidence": [{"source": "db", "reference": "x", "detail": "y", "confidence": "high"}],
                    },
                },
            ],
        )
        assert result["passed"] is False
        assert result["final_status"] == "failed"


class TestRootCauseRankingFiltersStaleDiagnose:
    def test_filters_cache_zero_when_exchange_has_orders(self):
        evidence = [
            {
                "source": "exchange",
                "reference": "reconciliation_counts",
                "detail": "Exchange=1, DB=1, dashboard=0",
                "confidence": "high",
            }
        ]
        tool_outputs = [
            {
                "tool": "diagnose_open_orders",
                "ok": True,
                "root_cause": "Database has pending orders but Crypto.com open orders cache is empty",
                "exchange_total_count": 1,
                "cache_raw_count": 0,
                "dashboard_effective_count": 1,
                "dashboard_source": "database_fallback",
            },
            {
                "tool": "reconcile_crypto_com_open_orders",
                "ok": True,
                "counts": {"exchange_live": 1, "database_open": 1, "dashboard_cache": 0},
                "root_cause": "Reconciliation found 2 discrepancy(ies)",
            },
        ]
        ranked = rank_root_causes(evidence=evidence, category="dashboard", tool_outputs=tool_outputs)
        causes = [c.cause for c in ranked]
        assert not any("api cache returned 0" in c.lower() for c in causes)
        assert any("fallback" in c.lower() or "reconciliation" in c.lower() for c in causes)
