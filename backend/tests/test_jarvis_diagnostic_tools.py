"""Tests for Jarvis read-only diagnostic tools."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.jarvis.execution.result_validation import validate_task_result
from app.jarvis.execution.service import submit_execution_task
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution_tools.query_database import _validate_select_only, query_database
from app.jarvis.execution_tools.diagnose_open_orders import diagnose_open_orders
from app.jarvis.execution_tools.search_repository import search_repository
from app.jarvis.execution_tools.search_logs import _redact_secrets, search_logs


class TestQueryDatabaseSafety:
    def test_accepts_select_query(self):
        _validate_select_only("SELECT COUNT(*) FROM exchange_orders")

    def test_rejects_insert(self):
        with pytest.raises(ValueError, match="SELECT"):
            _validate_select_only("INSERT INTO exchange_orders VALUES (1)")

    def test_rejects_update(self):
        with pytest.raises(ValueError, match="forbidden"):
            _validate_select_only("SELECT 1; UPDATE exchange_orders SET status='X'")

    def test_rejects_delete(self):
        with pytest.raises(ValueError, match="SELECT|forbidden"):
            _validate_select_only("DELETE FROM exchange_orders")

    @patch("app.jarvis.execution_tools.query_database._execute_query")
    def test_count_open_orders_returns_numeric_result(self, mock_exec):
        mock_exec.return_value = {
            "query_executed": "SELECT COUNT(*) ...",
            "row_count": 1,
            "rows": [{"count": 42}],
            "read_only": True,
            "checked_at": "2026-01-01T00:00:00+00:00",
        }
        result = query_database(preset="count_open_orders")
        assert result["ok"] is True
        assert result["count"] == 42
        assert result["numeric_result"] == 42


class TestDiagnoseOpenOrders:
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    @patch("app.jarvis.execution_tools.diagnose_open_orders.query_database")
    def test_returns_evidence(self, mock_query, mock_cache):
        def _side_effect(*, preset=None, **kwargs):
            if preset == "count_open_orders":
                return {"ok": True, "count": 0, "numeric_result": 0, "query_executed": "SELECT COUNT(*)", "row_count": 1, "rows": [{"count": 0}]}
            if preset == "count_orders_by_status":
                return {"ok": True, "status_counts": {}, "query_executed": "SELECT status", "row_count": 0, "rows": []}
            if preset == "recent_orders":
                return {"ok": True, "rows": [], "query_executed": "SELECT id", "row_count": 0}
            if preset == "open_positions":
                return {"ok": True, "rows": [], "query_executed": "SELECT symbol", "row_count": 0}
            return {"ok": True, "rows": [], "query_executed": "", "row_count": 0}

        mock_query.side_effect = _side_effect
        mock_cache.return_value = (0, {"source": "api", "reference": "cache", "detail": "empty", "confidence": "high"})

        result = diagnose_open_orders(objective="Why are open orders empty?")
        assert result["ok"] is True
        assert result["root_cause"]
        assert len(result["evidence"]) >= 3
        assert all("source" in e and "reference" in e and "detail" in e for e in result["evidence"])
        assert result["conclusion"]
        assert result["next_action"]


class TestSearchRepository:
    @patch("app.jarvis.execution_tools.search_repository.search_files")
    def test_returns_matching_files_and_lines(self, mock_search):
        mock_search.return_value = [
            {"path": "backend/app/api/routes_orders.py", "line": "1041", "text": "def get_open_orders("},
            {"path": "frontend/src/app/api.ts", "line": "678", "text": "export async function getOpenOrders"},
        ]
        result = search_repository(topic="open_orders")
        assert result["match_count"] >= 1
        match = result["matches"][0]
        assert match["path"]
        assert match["line"]
        assert match.get("confidence") in {"low", "medium", "high"}


class TestSearchLogs:
    def test_redacts_secrets(self):
        raw = "api_key=supersecret12345 password= hunter2"
        redacted = _redact_secrets(raw)
        assert "supersecret" not in redacted
        assert "REDACTED" in redacted

    @patch("app.jarvis.execution_tools.search_logs._fetch_docker_logs")
    def test_caps_output(self, mock_logs):
        mock_logs.return_value = [
            f"backend-aws | 2026-01-01 orders line {i} api_key=abc123"
            for i in range(100)
        ]
        result = search_logs(keyword="orders", max_matches=10)
        assert result["match_count"] <= 10
        for match in result["matches"]:
            assert "REDACTED" in match["message"] or "api_key" not in match["message"].lower()


class TestValidationWithDiagnostics:
    def test_why_open_orders_can_complete_with_diagnostic(self):
        result = validate_task_result(
            objective="Why are open orders empty?",
            task_type="investigation",
            tool_results=[
                {
                    "action": "diagnose_open_orders",
                    "tool": "diagnose_open_orders",
                    "ok": True,
                    "output": {
                        "root_cause": "No orders exist in exchange_orders table and open orders cache is empty",
                        "conclusion": "Database and cache are both empty.",
                        "next_action": "Verify Crypto.com API credentials.",
                        "evidence": [
                            {
                                "source": "database",
                                "reference": "exchange_orders",
                                "detail": "Open-status count: 0",
                                "confidence": "high",
                            }
                        ],
                    },
                }
            ],
            repo_investigation={"queries": ["open orders"]},
        )
        assert result["passed"] is True
        assert result["final_status"] == "completed"
        assert result["structured_evidence"]

    def test_count_open_orders_completes_with_numeric(self):
        result = validate_task_result(
            objective="Count how many open orders exist in the database",
            task_type="numeric",
            tool_results=[
                {
                    "action": "count_open_orders",
                    "tool": "query_database",
                    "ok": True,
                    "output": {"count": 17, "numeric_result": 17, "query_executed": "SELECT COUNT(*)", "row_count": 1},
                }
            ],
        )
        assert result["passed"] is True
        assert result["numeric_result"] == 17


class TestExecutionIntegrationWithDiagnostics:
    @pytest.fixture()
    def exec_db(self, monkeypatch, tmp_path):
        from sqlalchemy import create_engine
        from sqlalchemy.pool import StaticPool

        from app.database import (
            ensure_jarvis_execution_log_table,
            ensure_jarvis_task_approvals_table,
            ensure_jarvis_task_runs_table,
        )
        from app.jarvis.execution import audit as audit_mod
        from app.jarvis.execution import persistence as persist_mod

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        ensure_jarvis_task_runs_table(engine)
        ensure_jarvis_execution_log_table(engine)
        ensure_jarvis_task_approvals_table(engine)
        monkeypatch.setattr(persist_mod, "engine", engine)
        monkeypatch.setattr(audit_mod, "engine", engine)
        from app.jarvis import artifacts as artifacts_pkg

        monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
        yield engine
        engine.dispose()

    @patch("app.jarvis.execution_tools.query_database._execute_query")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    def test_count_orders_completes(self, mock_cache, mock_exec, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        mock_exec.return_value = {
            "query_executed": "SELECT COUNT(*) AS count FROM exchange_orders ...",
            "row_count": 1,
            "rows": [{"count": 5}],
            "read_only": True,
            "checked_at": "2026-01-01T00:00:00+00:00",
        }
        mock_cache.return_value = (5, {"source": "api", "reference": "cache", "detail": "5 orders", "confidence": "high"})

        detail = submit_execution_task(
            objective="Count how many open orders exist in the database",
            dry_run=True,
        )
        assert detail["status"] == TaskLifecycleState.COMPLETED.value
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is True
        assert validation.get("numeric_result") == 5

    @patch("app.jarvis.execution_tools.query_database._execute_query")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    def test_why_open_orders_completes(self, mock_cache, mock_exec, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")

        def _exec_side(query, *, limit):
            if "COUNT(*)" in query and "GROUP BY" not in query:
                return {"query_executed": query, "row_count": 1, "rows": [{"count": 0}], "read_only": True, "checked_at": ""}
            return {"query_executed": query, "row_count": 0, "rows": [], "read_only": True, "checked_at": ""}

        mock_exec.side_effect = _exec_side
        mock_cache.return_value = (0, {"source": "api", "reference": "cache", "detail": "empty", "confidence": "high"})

        detail = submit_execution_task(objective="Why are open orders empty?", dry_run=True)
        assert detail["status"] == TaskLifecycleState.COMPLETED.value
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is True
        assert validation.get("root_cause")

    @patch("app.jarvis.execution_tools.query_database._execute_query")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    def test_diagnose_end_to_end_completes(self, mock_cache, mock_exec, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")

        def _exec_side(query, *, limit):
            if "COUNT(*)" in query and "GROUP BY" not in query:
                return {"query_executed": query, "row_count": 1, "rows": [{"count": 3}], "read_only": True, "checked_at": ""}
            if "GROUP BY status" in query:
                return {"query_executed": query, "row_count": 2, "rows": [{"status": "ACTIVE", "count": 3}], "read_only": True, "checked_at": ""}
            return {"query_executed": query, "row_count": 1, "rows": [{"id": 1, "symbol": "BTC_USDT"}], "read_only": True, "checked_at": ""}

        mock_exec.side_effect = _exec_side
        mock_cache.return_value = (3, {"source": "api", "reference": "cache", "detail": "3 orders", "confidence": "high"})

        detail = submit_execution_task(objective="Diagnose open orders end-to-end", dry_run=True)
        assert detail["status"] == TaskLifecycleState.COMPLETED.value
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is True
        report = validation.get("completion_report") or {}
        assert report.get("evidence")
        assert report.get("conclusion")
        assert report.get("next_action")
