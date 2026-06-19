"""Tests for objective-aware Jarvis investigation routing and evidence gates."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis import router as jarvis_router
from app.database import (
    ensure_jarvis_execution_log_table,
    ensure_jarvis_task_approvals_table,
    ensure_jarvis_task_runs_table,
)
from app.jarvis.agents.planner_agent import build_plan
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.result_validation import validate_task_result
from app.jarvis.execution.service import submit_execution_task
from app.jarvis.investigations.objective_classification import (
    InvestigationObjectiveType,
    assess_order_reconciliation_evidence,
    classify_investigation_objective,
)


SPANISH_ORDER_OBJECTIVE = (
    "Jarvis, revisa por qué hay órdenes abiertas en el exchange que no aparecen en el dashboard"
)
ENGLISH_ORDER_OBJECTIVE = (
    "Why are there open orders in the exchange that do not appear in the dashboard"
)

ORDER_PLAN_ACTIONS = {
    "inspect_exchange_open_orders_readonly",
    "inspect_dashboard_open_orders_readonly",
    "compare_open_orders_readonly",
    "inspect_exchange_sync_mapping_readonly",
    "inspect_relevant_logs_readonly",
    "produce_order_reconciliation_report",
}


@pytest.fixture()
def exec_db(monkeypatch, tmp_path):
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
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_DIR", tmp_path / "repo")
    monkeypatch.setattr("app.jarvis.repository.persistence._METADATA_FILE", tmp_path / "repo" / "meta.json")
    yield engine
    engine.dispose()


@pytest.fixture()
def jarvis_client(exec_db, monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", exec_db)
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


class TestObjectiveClassification:
    def test_spanish_order_mismatch_routes_to_order_reconciliation(self):
        assert classify_investigation_objective(SPANISH_ORDER_OBJECTIVE) == InvestigationObjectiveType.ORDER_RECONCILIATION

    def test_english_order_mismatch_routes_to_order_reconciliation(self):
        assert classify_investigation_objective(ENGLISH_ORDER_OBJECTIVE) == InvestigationObjectiveType.ORDER_RECONCILIATION

    def test_generic_health_routes_to_deployment_health(self):
        assert classify_investigation_objective("Inspect deployment health and container status") == (
            InvestigationObjectiveType.DEPLOYMENT_HEALTH
        )

    def test_repository_architecture_routes_to_repository_analysis(self):
        assert classify_investigation_objective("Explain current Jarvis architecture and module map") == (
            InvestigationObjectiveType.REPOSITORY_ANALYSIS
        )


class TestPlanBuilder:
    def test_order_reconciliation_plan_contains_required_steps(self):
        plan = build_plan(SPANISH_ORDER_OBJECTIVE)
        assert plan.investigation_type == InvestigationObjectiveType.ORDER_RECONCILIATION.value
        actions = {step.action for step in plan.steps}
        tools = {step.tool for step in plan.steps}
        assert ORDER_PLAN_ACTIONS.issubset(actions)
        assert "reconcile_crypto_com_open_orders" in tools
        assert "diagnose_open_orders" in tools
        assert "search_logs" in tools

    def test_spanish_objective_does_not_use_generic_jarvis_health_plan(self):
        plan = build_plan(SPANISH_ORDER_OBJECTIVE)
        tools = [step.tool for step in plan.steps]
        assert tools != ["inspect_repository", "inspect_runtime", "inspect_health"]
        assert "inspect_health" not in tools

    def test_deployment_health_plan(self):
        plan = build_plan("Inspect deployment health")
        assert plan.investigation_type == InvestigationObjectiveType.DEPLOYMENT_HEALTH.value
        assert any(step.tool == "inspect_health" for step in plan.steps)


class TestSupervisorEvidenceGates:
    def test_rejects_completed_when_order_objective_has_no_order_evidence(self):
        result = validate_task_result(
            objective=SPANISH_ORDER_OBJECTIVE,
            task_type="investigation",
            tool_results=[
                {"tool": "inspect_repository", "ok": True, "output": {"modules": 12, "read_only": True}},
                {"tool": "inspect_runtime", "ok": True, "output": {"jarvis_enabled": True}},
                {"tool": "inspect_health", "ok": True, "output": {"status": "ok", "endpoints_checked": 2}},
            ],
            repo_investigation={"queries": ["jarvis"]},
            final_answer="Health checks passed",
        )
        assert result["passed"] is False
        assert result["final_status"] == "insufficient_evidence"
        assert result["investigation_type"] == InvestigationObjectiveType.ORDER_RECONCILIATION.value
        labels = {c["label"]: c["passed"] for c in result["checks"]}
        assert labels["Not only generic health/repo tools"] is False

    def test_accepts_completed_when_order_objective_has_required_evidence(self):
        result = validate_task_result(
            objective=ENGLISH_ORDER_OBJECTIVE,
            task_type="investigation",
            tool_results=[
                {
                    "tool": "reconcile_crypto_com_open_orders",
                    "ok": True,
                    "output": {
                        "counts": {"exchange_live": 2, "database_open": 1, "dashboard_cache": 1},
                        "discrepancies": [{"order_id": "abc"}],
                        "root_cause": "Exchange has one trigger order missing from dashboard cache sync path",
                    },
                },
                {
                    "tool": "diagnose_open_orders",
                    "ok": True,
                    "output": {
                        "exchange_total_count": 2,
                        "dashboard_effective_count": 1,
                        "root_cause": "Trigger order sync lag leaves exchange-only open order visible",
                        "conclusion": "Dashboard under-reports one exchange open order",
                        "evidence": [
                            {
                                "source": "exchange",
                                "reference": "live",
                                "detail": "exchange=2 dashboard=1",
                                "confidence": "high",
                            }
                        ],
                    },
                },
                {
                    "tool": "search_repository",
                    "ok": True,
                    "output": {"topic": "exchange_sync", "match_count": 2, "matches": [{"path": "exchange_sync.py"}]},
                },
            ],
            repo_investigation={"queries": ["open orders"]},
        )
        assert result["passed"] is True
        assert result["final_status"] == "completed"
        assert result["order_evidence"]["sufficient"] is True


class TestOrderEvidenceAssessment:
    def test_assess_marks_missing_when_only_generic_tools(self):
        assessment = assess_order_reconciliation_evidence(
            [
                {"tool": "inspect_health", "ok": True, "output": {"status": "ok"}},
                {"tool": "inspect_repository", "ok": True, "output": {"modules": 3}},
            ]
        )
        assert assessment["only_generic_tools"] is True
        assert assessment["sufficient"] is False


class TestApiEndpoints:
    def test_approval_queue_returns_empty_when_no_db(self, monkeypatch):
        import app.database as db_mod

        monkeypatch.setattr(db_mod, "engine", None)
        app = FastAPI()
        app.include_router(jarvis_router)
        client = TestClient(app)
        resp = client.get("/api/jarvis/approval-queue")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_approval_queue_returns_200_with_empty_queue(self, jarvis_client):
        resp = jarvis_client.get("/api/jarvis/approval-queue")
        assert resp.status_code == 200
        assert resp.json()["items"] == []

    def test_submit_task_does_not_return_500_for_valid_objective(self, jarvis_client):
        with patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_live_exchange") as mock_exchange, patch(
            "app.jarvis.execution_tools.diagnose_open_orders._inspect_dashboard_effective"
        ) as mock_dashboard, patch(
            "app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache"
        ) as mock_cache, patch(
            "app.jarvis.execution_tools.query_database._execute_query"
        ) as mock_query, patch(
            "app.jarvis.execution_tools.reconcile_crypto_com_open_orders._fetch_exchange_orders"
        ) as mock_reconcile_exchange, patch(
            "app.jarvis.execution_tools.reconcile_crypto_com_open_orders._fetch_db_open_orders"
        ) as mock_reconcile_db, patch(
            "app.jarvis.execution_tools.reconcile_crypto_com_open_orders._fetch_dashboard_orders"
        ) as mock_reconcile_dash:
            mock_cache.return_value = (0, {"source": "api", "reference": "cache", "detail": "empty", "confidence": "high"})
            mock_dashboard.return_value = (
                1,
                "database_fallback",
                "stale",
                {"source": "dashboard", "reference": "resolve", "detail": "effective=1", "confidence": "high"},
            )
            mock_exchange.return_value = (
                {
                    "regular_count": 1,
                    "trigger_count": 0,
                    "total_count": 1,
                    "data_verified": True,
                    "skipped": False,
                },
                {"source": "exchange", "reference": "live", "detail": "regular=1", "confidence": "high"},
            )
            mock_query.side_effect = lambda query, *, limit: {
                "query_executed": query,
                "row_count": 1 if "COUNT(*)" in query else 0,
                "rows": [{"count": 1}] if "COUNT(*)" in query else [],
                "read_only": True,
                "checked_at": "",
            }
            mock_reconcile_exchange.return_value = (
                [{"order_id": "1", "symbol": "BTC_USDT", "status": "ACTIVE", "source": "exchange"}],
                {"regular_count": 1, "trigger_count": 0, "skipped": False, "error": None},
            )
            mock_reconcile_db.return_value = (
                [{"order_id": "1", "symbol": "BTC_USDT", "status": "ACTIVE", "source": "database"}],
                {"count": 1},
            )
            mock_reconcile_dash.return_value = ([], {"count": 0})

            resp = jarvis_client.post(
                "/api/jarvis/tasks/submit",
                json={"objective": SPANISH_ORDER_OBJECTIVE, "dry_run": True},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["plan"]["investigation_type"] == InvestigationObjectiveType.ORDER_RECONCILIATION.value
        plan_tools = {step["tool"] for step in body["plan"]["steps"]}
        assert "reconcile_crypto_com_open_orders" in plan_tools
        assert "diagnose_open_orders" in plan_tools


class TestRegressionSpanishObjective:
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_live_exchange")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_dashboard_effective")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    @patch("app.jarvis.execution_tools.query_database._execute_query")
    def test_spanish_objective_not_only_generic_health_tools(
        self, mock_query, mock_cache, mock_dashboard, mock_exchange, exec_db, monkeypatch
    ):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        mock_cache.return_value = (0, {"source": "api", "reference": "cache", "detail": "empty", "confidence": "high"})
        mock_dashboard.return_value = (
            0,
            "crypto.com",
            "ok",
            {"source": "dashboard", "reference": "resolve", "detail": "effective=0", "confidence": "high"},
        )
        mock_exchange.return_value = (
            {"regular_count": 0, "trigger_count": 0, "total_count": 0, "data_verified": True, "skipped": False},
            {"source": "exchange", "reference": "live", "detail": "zero", "confidence": "high"},
        )
        mock_query.side_effect = lambda query, *, limit: {
            "query_executed": query,
            "row_count": 1 if "COUNT(*)" in query and "GROUP BY" not in query else 0,
            "rows": [{"count": 0}] if "COUNT(*)" in query and "GROUP BY" not in query else [],
            "read_only": True,
            "checked_at": "",
        }

        detail = submit_execution_task(objective=SPANISH_ORDER_OBJECTIVE, dry_run=True)
        tools = [r.get("tool") for r in detail.get("tool_results") or []]
        assert "inspect_repository" not in tools or "diagnose_open_orders" in tools
        assert detail["plan"]["investigation_type"] == InvestigationObjectiveType.ORDER_RECONCILIATION.value
        assert detail["status"] in {
            TaskLifecycleState.COMPLETED.value,
            TaskLifecycleState.INSUFFICIENT_EVIDENCE.value,
            TaskLifecycleState.FAILED.value,
        }
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("investigation_type") == InvestigationObjectiveType.ORDER_RECONCILIATION.value
