"""Tests for Jarvis supervisor result-quality validation gates."""

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
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.execution.change_service import submit_change_task
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.result_validation import (
    classify_task_type,
    validate_task_result,
)
from app.jarvis.execution.service import submit_execution_task


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


class TestTaskTypeClassification:
    def test_investigation_prompt(self):
        assert classify_task_type("Why are open orders empty?") == "investigation"

    def test_numeric_prompt(self):
        assert classify_task_type("Count how many open orders exist in the database") == "numeric"

    def test_patch_prompt(self):
        assert classify_task_type("Create a patch to fix empty open orders") == "patch"

    def test_remediation_prompt(self):
        assert classify_task_type("Fix the websocket reconnect bug") == "remediation"


class TestValidationGates:
    def test_investigation_without_root_cause_fails(self):
        result = validate_task_result(
            objective="Why are open orders empty?",
            task_type="investigation",
            tool_results=[
                {
                    "action": "identify_root_cause",
                    "ok": True,
                    "output": {"root_cause": None, "status": "ok"},
                }
            ],
            repo_investigation={"queries": ["open orders"]},
            final_answer="identify_root_cause: None",
        )
        assert result["passed"] is False
        assert result["final_status"] == "insufficient_evidence"
        labels = {c["label"]: c["passed"] for c in result["checks"]}
        assert labels["Root cause present"] is False

    def test_investigation_with_root_cause_passes(self):
        result = validate_task_result(
            objective="Why are open orders empty?",
            task_type="investigation",
            tool_results=[
                {
                    "action": "identify_root_cause",
                    "ok": True,
                    "output": {
                        "root_cause": "Orders API filters out zero-qty rows in routes_orders.py line 42",
                    },
                }
            ],
            repo_investigation={
                "queries": ["open orders"],
                "findings": {"routes_orders.py": [{"path": "backend/app/api/routes_orders.py"}]},
            },
            final_answer="Root cause identified in routes_orders.py",
        )
        assert result["passed"] is True
        assert result["final_status"] == "completed"
        assert result["root_cause"]

    def test_numeric_without_answer_fails(self):
        result = validate_task_result(
            objective="Count how many open orders exist in the database",
            task_type="numeric",
            tool_results=[{"action": "inspect_repository", "ok": True, "output": {"read_only": True}}],
            final_answer="inspect_repository: ok",
        )
        assert result["passed"] is False
        assert result["final_status"] == "failed"
        assert "numeric" in result["explanation"].lower()

    def test_numeric_with_answer_passes(self):
        result = validate_task_result(
            objective="Count how many open orders exist in the database",
            task_type="numeric",
            tool_results=[{"action": "count_orders", "ok": True, "output": {"count": 17}}],
            final_answer="count: 17",
        )
        assert result["passed"] is True
        assert result["numeric_result"] == 17

    def test_patch_without_diff_fails(self):
        result = validate_task_result(
            objective="Create a patch to fix empty open orders",
            task_type="patch",
            artifacts=[],
        )
        assert result["passed"] is False
        assert result["final_status"] == "failed"
        labels = {c["label"]: c["passed"] for c in result["checks"]}
        assert labels["Patch present"] is False

    def test_remediation_without_plan_fails(self):
        result = validate_task_result(
            objective="Fix empty open orders in the dashboard",
            task_type="remediation",
            tool_results=[
                {
                    "action": "identify_root_cause",
                    "ok": True,
                    "output": {"root_cause": "Cache TTL too short"},
                }
            ],
        )
        assert result["passed"] is False
        labels = {c["label"]: c["passed"] for c in result["checks"]}
        assert labels["Root cause present"] is True
        assert labels["Remediation plan present"] is False

    def test_patch_workflow_waiting_for_approval(self):
        result = validate_task_result(
            objective="Create a patch to fix empty open orders",
            task_type="patch",
            artifacts=[
                {
                    "standard_name": "patch.diff",
                    "preview": "--- a/backend/app/main.py\n+++ b/backend/app/main.py\n",
                }
            ],
            workflow_type="phase4_change",
        )
        assert result["passed"] is True
        assert result["final_status"] == "waiting_for_approval"


class TestExecutionIntegration:
    @patch("app.jarvis.execution_tools.query_database._execute_query")
    @patch("app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache")
    def test_why_open_orders_completes_with_diagnostics(self, mock_cache, mock_exec, exec_db, monkeypatch):
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

    @patch("app.jarvis.execution_tools.query_database._execute_query")
    def test_count_orders_completes_with_numeric(self, mock_exec, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        mock_exec.return_value = {
            "query_executed": "SELECT COUNT(*) ...",
            "row_count": 1,
            "rows": [{"count": 12}],
            "read_only": True,
            "checked_at": "",
        }
        detail = submit_execution_task(
            objective="Count how many open orders exist in the database",
            dry_run=True,
        )
        assert detail["status"] == TaskLifecycleState.COMPLETED.value
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is True
        assert validation.get("numeric_result") == 12

    def test_why_open_orders_not_completed_without_diagnostics(self, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        detail = submit_execution_task(objective="Why is websocket reconnect failing?", dry_run=True)
        assert detail["status"] in {
            TaskLifecycleState.FAILED.value,
            TaskLifecycleState.INSUFFICIENT_EVIDENCE.value,
        }
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is False

    @patch("app.jarvis.execution_tools.query_database._execute_query")
    def test_count_orders_fails_without_db(self, mock_exec, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        mock_exec.side_effect = Exception("no such table: exchange_orders")
        detail = submit_execution_task(
            objective="Count how many open orders exist in the database",
            dry_run=True,
        )
        assert detail["status"] == TaskLifecycleState.FAILED.value
        assert "numeric" in ((detail.get("review") or {}).get("validation") or {}).get("explanation", "").lower()

    def test_patch_request_via_execution_fails(self, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        detail = submit_execution_task(objective="Create a patch to fix empty open orders", dry_run=True)
        assert detail["status"] == TaskLifecycleState.FAILED.value

    def test_operational_inspection_still_completes(self, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        detail = submit_execution_task(objective="Inspect deployment health", dry_run=True)
        assert detail["status"] == TaskLifecycleState.COMPLETED.value
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is True

    def test_change_workflow_waiting_for_approval(self, exec_db, monkeypatch):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        detail = submit_change_task(objective="Create a patch to fix empty open orders", dry_run=True, run_tests=False)
        assert detail["status"] == TaskLifecycleState.WAITING_FOR_APPROVAL.value
        validation = (detail.get("review") or {}).get("validation") or {}
        assert validation.get("passed") is True
        assert validation.get("final_status") == "waiting_for_approval"


class TestValidationApiSurface:
    def test_execution_detail_includes_validation(self, exec_db, monkeypatch, tmp_path):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        import app.database as db_mod

        monkeypatch.setattr(db_mod, "engine", exec_db)
        from app.jarvis import artifacts as artifacts_pkg

        monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
        app = FastAPI()
        app.include_router(jarvis_router)
        client = TestClient(app)
        with patch("app.jarvis.execution_tools.query_database._execute_query") as mock_exec, patch(
            "app.jarvis.execution_tools.diagnose_open_orders._inspect_open_orders_cache"
        ) as mock_cache:
            mock_exec.side_effect = lambda query, *, limit: {
                "query_executed": query,
                "row_count": 1 if "COUNT(*)" in query and "GROUP BY" not in query else 0,
                "rows": [{"count": 0}] if "COUNT(*)" in query and "GROUP BY" not in query else [],
                "read_only": True,
                "checked_at": "",
            }
            mock_cache.return_value = (0, {"source": "api", "reference": "cache", "detail": "empty", "confidence": "high"})
            submit = client.post(
                "/api/jarvis/tasks/submit",
                json={"objective": "Why are open orders empty?", "dry_run": True},
            )
        assert submit.status_code == 200
        task_id = submit.json()["task_id"]
        detail = client.get(f"/api/jarvis/tasks/execution/{task_id}")
        assert detail.status_code == 200
        body = detail.json()
        assert body["review"]["validation"]["passed"] is True
        assert body["review"]["validation"]["root_cause"]

    def test_agent_pipeline_includes_validation(self, exec_db, monkeypatch, tmp_path):
        monkeypatch.setenv("JARVIS_ENABLED", "true")
        import app.database as db_mod

        monkeypatch.setattr(db_mod, "engine", exec_db)
        from app.jarvis import artifacts as artifacts_pkg

        monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
        app = FastAPI()
        app.include_router(jarvis_router)
        client = TestClient(app)
        with patch("app.jarvis.execution_tools.query_database._execute_query") as mock_exec:
            mock_exec.return_value = {
                "query_executed": "SELECT COUNT(*) ...",
                "row_count": 1,
                "rows": [{"count": 9}],
                "read_only": True,
                "checked_at": "",
            }
            submit = client.post(
                "/api/jarvis/tasks/submit",
                json={"objective": "Count how many open orders exist in the database", "dry_run": True},
            )
        task_id = submit.json()["task_id"]
        pipeline = client.get(f"/api/jarvis/tasks/execution/{task_id}/agents")
        assert pipeline.status_code == 200
        assert pipeline.json()["validation"]["passed"] is True
        assert pipeline.json()["validation"]["numeric_result"] == 9
