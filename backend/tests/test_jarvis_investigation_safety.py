"""Tests for Jarvis read-only investigation safety classification."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes_jarvis import router as jarvis_router
from app.jarvis.agents.planner_agent import build_plan
from app.jarvis.change_execution.config import phase5_safety_status
from app.jarvis.execution.safety import (
    SafetyLevel,
    classify_text,
    classify_text_with_reason,
    has_destructive_intent,
)
from app.jarvis.execution.service import submit_execution_task
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.result_validation import validate_task_result


@pytest.mark.parametrize(
    "objective",
    [
        "Why are open orders different from Crypto.com?",
        "Why are executed orders missing?",
        "Investigate portfolio reconciliation mismatch",
        "Investigate reconciliation mismatch between database and Crypto.com",
        "Explain discrepancy in open orders",
        "Investigate BTC open orders without placing trades",
        "Read logs and explain why orders are missing",
        "executed orders is missing orders. for example btc orders $19,398.03 in dashboard wallet orders are not visible",
        "trade orders missing from dashboard wallet",
        "why are my trade orders not showing on dashboard",
        "investigate executed trade history mismatch",
    ],
)
def test_investigation_objectives_are_safe_auto(objective: str):
    reason = classify_text_with_reason(objective)
    assert reason["level"] == SafetyLevel.SAFE_AUTO.value, reason
    assert reason["category"] in {"read_only_investigation", "default"}


@pytest.mark.parametrize(
    "objective",
    [
        "Investigate and execute trade if missing orders are detected",
        "Investigate missing BTC orders and place replacement orders",
        "Investigate discrepancy and cancel all open orders",
        "Investigate portfolio mismatch and buy BTC",
        "Investigate open orders and sell ETH",
        "Investigate order issue and close position",
        "Investigate order issue and open position",
        "Execute market order after checking logs",
        "Open a BTC position after investigating logs",
        "Close all positions after checking reconciliation",
    ],
)
def test_destructive_investigation_objectives_are_forbidden(objective: str):
    reason = classify_text_with_reason(objective)
    assert reason["level"] == SafetyLevel.FORBIDDEN.value, reason
    assert has_destructive_intent(objective)
    plan = build_plan(objective)
    assert plan.overall_safety == SafetyLevel.FORBIDDEN.value
    assert plan.steps == []


@pytest.mark.parametrize(
    "objective",
    [
        "Why are open orders different from Crypto.com?",
        "Why are executed orders missing?",
        "Investigate portfolio reconciliation mismatch",
    ],
)
def test_investigation_planner_produces_evidence_steps(objective: str):
    plan = build_plan(objective)
    assert plan.overall_safety == SafetyLevel.SAFE_AUTO.value
    assert len(plan.steps) >= 3
    tools = {step.tool for step in plan.steps}
    assert "search_logs" in tools or "read_logs" in tools
    assert "diagnose_open_orders" in tools or "query_database" in tools or "reconcile_crypto_com_open_orders" in tools
    assert "search_repository" in tools or "inspect_repository" in tools
    for step in plan.steps:
        assert classify_text(step.action) != SafetyLevel.FORBIDDEN
        assert classify_text(step.tool.replace("_", " ")) != SafetyLevel.FORBIDDEN


@pytest.mark.parametrize(
    "objective",
    [
        "execute trade order immediately",
        "place order on exchange now",
        "delete s3 bucket resources",
        "deploy to production",
        "delete production data",
        "merge to main",
        "modify secrets in production",
    ],
)
def test_destructive_objectives_remain_forbidden(objective: str):
    assert classify_text(objective) == SafetyLevel.FORBIDDEN


@pytest.mark.parametrize(
    "objective",
    [
        "Investigate Jarvis validation framework. Do not deploy.",
        "Inspect recent tasks. Do not create patches. Do not deploy.",
        "Investigate result_validation.py logic. Do not merge. Report only.",
        "Audit planner_agent.py code paths. Do not modify secrets.",
    ],
)
def test_negated_safety_constraints_are_safe_auto(objective: str):
    reason = classify_text_with_reason(objective)
    assert reason["level"] == SafetyLevel.SAFE_AUTO.value, reason


@pytest.mark.parametrize(
    "objective",
    [
        "Deploy to production. Do not deploy backups.",
        "Investigate outage. Do not deploy. Merge to main.",
        "Inspect logs. Do not deploy. Delete production data.",
    ],
)
def test_mixed_objective_affirmative_dangerous_action_is_forbidden(objective: str):
    reason = classify_text_with_reason(objective)
    assert reason["level"] == SafetyLevel.FORBIDDEN.value, reason
    assert has_destructive_intent(objective) or reason["category"] == "forbidden_pattern"


def test_trade_orders_investigation_not_blocked_by_old_trade_pattern():
    objective = "trade orders missing from dashboard wallet"
    reason = classify_text_with_reason(objective)
    assert reason["level"] == SafetyLevel.SAFE_AUTO.value
    assert reason["rule"] == "investigation_intent"


def test_phase5_write_gates_remain_disabled(monkeypatch):
    monkeypatch.delenv("JARVIS_PATCH_APPLY_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_PR_CREATION_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_WRITE_ENABLED", raising=False)
    status = phase5_safety_status()
    assert status["patch_apply_enabled"] is False
    assert status["pr_creation_enabled"] is False
    assert status["github_write_enabled"] is False


def test_planner_never_schedules_write_or_trading_tools():
    plan = build_plan("Why are executed orders missing?")
    write_actions = {"deploy", "trading", "patch_application", "create_pr", "merge"}
    for step in plan.steps:
        assert step.action not in write_actions
        assert step.tool not in write_actions


def test_empty_tool_outputs_yield_insufficient_evidence():
    result = validate_task_result(
        objective="Why are executed orders missing?",
        task_type="investigation",
        tool_results=[
            {"action": "read_logs", "tool": "read_logs", "ok": True, "output": {"status": "ok", "read_only": True}},
            {"action": "search_logs", "tool": "search_logs", "ok": True, "output": {"ok": True, "matches": []}},
        ],
        artifacts=[{"name": "read_logs_output", "content": {"status": "ok"}}],
    )
    assert result["passed"] is False
    assert result["final_status"] == "insufficient_evidence"


def test_successful_investigation_requires_real_evidence_and_conclusion():
    result = validate_task_result(
        objective="Why are executed orders missing?",
        task_type="investigation",
        tool_results=[
            {
                "tool": "diagnose_open_orders",
                "action": "run_investigation",
                "ok": True,
                "output": {
                    "root_cause": "Exchange sync job skipped rows with status FILLED during migration window",
                    "conclusion": "Missing orders are stale DB rows not refreshed after exchange migration",
                    "evidence": [
                        {
                            "source": "database",
                            "reference": "exchange_orders",
                            "detail": "42 executed orders missing updated_at after migration",
                            "confidence": "high",
                        }
                    ],
                },
            },
            {
                "tool": "search_logs",
                "action": "search_logs",
                "ok": True,
                "output": {
                    "match_count": 1,
                    "matches": [{"source": "sync", "message": "skipped FILLED orders during migration"}],
                },
            },
        ],
        artifacts=[
            {
                "name": "run_investigation_output",
                "content": {
                    "root_cause": "Exchange sync job skipped rows with status FILLED during migration window",
                    "evidence": [{"detail": "42 executed orders missing updated_at"}],
                },
            }
        ],
    )
    assert result["passed"] is True
    assert result["final_status"] == "completed"
    assert result["root_cause"]


def test_failed_tools_do_not_pretend_success():
    result = validate_task_result(
        objective="Why are executed orders missing?",
        task_type="investigation",
        tool_results=[
            {"tool": "query_database", "action": "query_database", "ok": False, "error": "connection refused"},
        ],
    )
    assert result["passed"] is False
    assert result["final_status"] == "failed"
    labels = {c["label"]: c["passed"] for c in result["checks"]}
    assert labels["Mandatory tool execution succeeded"] is False


@pytest.fixture()
def jarvis_exec_client(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


@pytest.fixture()
def exec_db(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool
    from app.database import (
        ensure_jarvis_execution_log_table,
        ensure_jarvis_task_approvals_table,
        ensure_jarvis_task_runs_table,
    )
    from app.jarvis.execution import audit as audit_mod
    from app.jarvis.execution import persistence as persist_mod
    import app.database as db_mod

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
    monkeypatch.setattr(db_mod, "engine", engine)
    yield engine
    engine.dispose()


def test_submit_task_without_images(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_execution_task(
        objective="Why are executed orders missing?",
        dry_run=True,
    )
    assert detail["status"] in {TaskLifecycleState.COMPLETED.value, TaskLifecycleState.INSUFFICIENT_EVIDENCE.value}
    assert detail["plan"]["overall_safety"] == SafetyLevel.SAFE_AUTO.value
    assert len(detail["plan"]["steps"]) >= 3


def test_submit_forbidden_task_fails_fast(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_execution_task(
        objective="Investigate and execute trade if missing orders are detected",
        dry_run=True,
    )
    assert detail["status"] == TaskLifecycleState.FAILED.value
    assert detail["plan"]["overall_safety"] == SafetyLevel.FORBIDDEN.value
    assert detail["plan"]["steps"] == []


def test_api_submit_safe_investigation(jarvis_exec_client):
    resp = jarvis_exec_client.post(
        "/api/jarvis/tasks/submit",
        json={
            "objective": "Why are executed orders missing?",
            "priority": "normal",
            "approval_mode": "auto",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"completed", "insufficient_evidence", "failed"}
    assert body["plan"]["overall_safety"] == SafetyLevel.SAFE_AUTO.value
