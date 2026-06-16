"""Tests for Jarvis Phase 3 task execution framework."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.pool import StaticPool

from app.api.routes_jarvis import router as jarvis_router
from app.database import (
    ensure_jarvis_execution_log_table,
    ensure_jarvis_task_approvals_table,
    ensure_jarvis_task_runs_table,
)
from app.jarvis.agents.planner_agent import build_plan
from app.jarvis.agents.repository_agent import investigate_objective, search_files
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.execution.cost_guard import CostGuard, CostGuardLimits, CostGuardViolation
from app.jarvis.execution.lifecycle import (
    InvalidTaskTransitionError,
    TaskLifecycleState,
    normalize_status,
    validate_transition,
)
from app.jarvis.execution.safety import SafetyLevel, classify_text
from app.jarvis.execution.service import approve_task, reject_task, submit_execution_task
from app.jarvis.execution_tools.registry import ToolRegistry, ToolSpec, build_default_registry


@pytest.fixture()
def exec_db(monkeypatch):
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
    yield engine
    engine.dispose()


@pytest.fixture()
def jarvis_client(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_DRY_RUN_ONLY", "true")
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", exec_db)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


# --- lifecycle (12 tests) ---


@pytest.mark.parametrize(
    "current,target",
    [
        ("queued", "planning"),
        ("planning", "executing"),
        ("planning", "waiting_for_approval"),
        ("waiting_for_approval", "executing"),
        ("executing", "completed"),
        ("executing", "failed"),
        ("planning", "failed"),
        ("queued", "cancelled"),
        ("waiting_for_approval", "cancelled"),
    ],
)
def test_lifecycle_valid_transitions(current, target):
    assert validate_transition(current, target).value == target


@pytest.mark.parametrize(
    "current,target",
    [
        ("completed", "executing"),
        ("failed", "planning"),
        ("cancelled", "queued"),
        ("queued", "completed"),
        ("executing", "planning"),
    ],
)
def test_lifecycle_invalid_transitions(current, target):
    with pytest.raises(InvalidTaskTransitionError):
        validate_transition(current, target)


@pytest.mark.parametrize(
    "legacy,expected",
    [
        ("running", "executing"),
        ("requires_approval", "waiting_for_approval"),
        ("completed", "completed"),
    ],
)
def test_normalize_legacy_status(legacy, expected):
    assert normalize_status(legacy).value == expected


def test_terminal_states():
    from app.jarvis.execution.lifecycle import is_terminal

    assert is_terminal("completed") is True
    assert is_terminal("executing") is False


# --- safety (10 tests) ---


@pytest.mark.parametrize(
    "text,level",
    [
        ("inspect deployment health", SafetyLevel.SAFE_AUTO),
        ("find websocket implementation", SafetyLevel.SAFE_AUTO),
        ("explain jarvis architecture", SafetyLevel.SAFE_AUTO),
        ("propose restart backend service", SafetyLevel.NEEDS_APPROVAL),
        ("deploy to production now", SafetyLevel.FORBIDDEN),
        ("execute trade order immediately", SafetyLevel.FORBIDDEN),
        ("delete s3 bucket resources", SafetyLevel.FORBIDDEN),
        ("modify secrets in production", SafetyLevel.FORBIDDEN),
        ("inspect running containers", SafetyLevel.SAFE_AUTO),
        ("change nginx config on prod", SafetyLevel.NEEDS_APPROVAL),
    ],
)
def test_classify_text_safety(text, level):
    assert classify_text(text) == level


# --- planner (8 tests) ---


@pytest.mark.parametrize(
    "objective,min_steps",
    [
        ("Inspect deployment health", 3),
        ("Find websocket implementation", 2),
        ("Explain current Jarvis architecture", 2),
        ("Identify all OpenClaw references", 2),
        ("Inspect running containers", 2),
    ],
)
def test_planner_builds_steps(objective, min_steps):
    plan = build_plan(objective)
    assert len(plan.steps) >= min_steps
    assert plan.total_estimated_cost_usd > 0
    assert plan.overall_safety == SafetyLevel.SAFE_AUTO.value


def test_planner_forbidden_objective_empty_plan():
    plan = build_plan("execute trade order on exchange now")
    assert plan.steps == []
    assert plan.overall_safety == SafetyLevel.FORBIDDEN.value


def test_planner_schema_validation():
    plan = build_plan("inspect deployment health")
    data = plan.model_dump()
    assert isinstance(data["steps"], list)
    assert data["steps"][0]["tool"] in build_default_registry().list_tools()


def test_planner_restart_needs_approval():
    plan = build_plan("restart backend service and deploy")
    assert plan.overall_safety in {SafetyLevel.NEEDS_APPROVAL.value, SafetyLevel.FORBIDDEN.value}


# --- cost guard (6 tests) ---


def test_cost_guard_estimated_limit():
    guard = CostGuard(CostGuardLimits(max_estimated_cost_usd=0.05))
    with pytest.raises(CostGuardViolation):
        guard.check_estimated_cost(1.0)


def test_cost_guard_step_limit():
    guard = CostGuard(CostGuardLimits(max_steps=2))
    guard.begin_step("a")
    guard.begin_step("b")
    with pytest.raises(CostGuardViolation):
        guard.begin_step("c")


def test_cost_guard_loop_detection():
    guard = CostGuard()
    guard.begin_step("same")
    with pytest.raises(CostGuardViolation):
        guard.begin_step("same")


def test_cost_guard_retry_limit():
    guard = CostGuard(CostGuardLimits(max_retries=1))
    guard.record_retry()
    with pytest.raises(CostGuardViolation):
        guard.record_retry()


def test_cost_guard_actual_cost():
    guard = CostGuard(CostGuardLimits(max_actual_cost_usd=0.05))
    with pytest.raises(CostGuardViolation):
        guard.record_cost(0.10)


def test_cost_guard_duration():
    guard = CostGuard(CostGuardLimits(max_duration_seconds=1.0))
    with pytest.raises(CostGuardViolation):
        guard.check_duration(5.0)


# --- tool registry (8 tests) ---


def test_default_registry_lists_six_tools():
    reg = build_default_registry()
    names = reg.list_tools()
    # Registry may include additional read-only diagnostic tools. We only
    # require the core Phase 3 tools to exist.
    assert len(names) >= 6
    for expected in (
        "read_logs",
        "inspect_container",
        "inspect_repository",
        "inspect_runtime",
        "inspect_health",
        "inspect_costs",
    ):
        assert expected in names


@pytest.mark.parametrize("tool_name", build_default_registry().list_tools())
def test_registry_executes_readonly_tool(tool_name):
    reg = build_default_registry()
    result = reg.execute(tool_name)
    assert result.tool == tool_name
    assert result.ok is True
    assert result.output.get("read_only") is True


def test_registry_unknown_tool():
    reg = build_default_registry()
    result = reg.execute("nonexistent_tool")
    assert result.ok is False


def test_registry_blocks_write_tool():
    reg = ToolRegistry()

    def write_tool() -> dict:
        return {"wrote": True}

    reg.register(ToolSpec(name="write_tool", description="x", handler=write_tool, read_only=False))
    result = reg.execute("write_tool")
    assert result.ok is False
    assert "disabled" in (result.error or "")


# --- repository agent (3 tests) ---


def test_repository_investigate_objective():
    result = investigate_objective("Find websocket implementation")
    assert result["read_only"] is True
    assert "websocket" in result["queries"][0].lower() or "websocket" in str(result["queries"]).lower()


def test_repository_search_files():
    hits = search_files("jarvis", max_results=5)
    assert isinstance(hits, list)


def test_repository_openclaw_query():
    result = investigate_objective("Identify all OpenClaw references")
    assert "openclaw" in str(result["queries"]).lower()


# --- persistence + service (8 tests) ---


def test_submit_task_completes_safe_auto(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_execution_task(objective="Inspect deployment health", dry_run=True)
    assert detail["status"] == TaskLifecycleState.COMPLETED.value
    assert detail["actual_cost_usd"] >= 0
    assert len(detail.get("artifacts") or []) >= 1
    assert len(detail.get("execution_log") or []) >= 1


def test_submit_forbidden_fails(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_execution_task(objective="execute trade order now", dry_run=True)
    assert detail["status"] == TaskLifecycleState.FAILED.value


def test_approval_workflow(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_execution_task(
        objective="restart backend service on production",
        approval_mode="auto",
        dry_run=True,
    )
    assert detail["status"] == TaskLifecycleState.WAITING_FOR_APPROVAL.value
    task_id = detail["task_id"]
    approved = approve_task(task_id, actor_id="tester", comment="ok")
    assert approved["status"] == TaskLifecycleState.COMPLETED.value
    assert approved["approvals"][-1]["decision"] == "approved"


def test_reject_workflow(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_execution_task(
        objective="restart nginx config on prod",
        approval_mode="manual",
        dry_run=True,
    )
    rejected = reject_task(detail["task_id"], actor_id="tester", comment="no")
    assert rejected["status"] == TaskLifecycleState.CANCELLED.value


def test_phase3_columns_exist(exec_db):
    cols = {c["name"] for c in inspect(exec_db).get_columns("jarvis_task_runs")}
    for name in ("objective", "artifacts_json", "approval_status", "actual_cost_usd", "started_at"):
        assert name in cols


def test_execution_log_table(exec_db):
    assert inspect(exec_db).has_table("jarvis_execution_log")


def test_approvals_table(exec_db):
    assert inspect(exec_db).has_table("jarvis_task_approvals")


def test_list_execution_tasks(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    submit_execution_task(objective="inspect health", dry_run=True)
    rows = persist_mod.list_execution_tasks(limit=5)
    assert len(rows) >= 1


# --- API routes (6 tests) ---


def test_api_submit(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "Inspect deployment health", "dry_run": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["task_id"]


def test_api_list_and_detail(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "Explain current Jarvis architecture", "dry_run": True},
    )
    task_id = submit.json()["task_id"]
    detail = jarvis_client.get(f"/api/jarvis/tasks/execution/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["objective"].startswith("Explain")


def test_api_approve_reject(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "restart backend", "approval_mode": "manual", "dry_run": True},
    )
    task_id = submit.json()["task_id"]
    reject = jarvis_client.post(
        f"/api/jarvis/tasks/{task_id}/reject",
        json={"actor_id": "tester", "comment": "nope"},
    )
    assert reject.status_code == 200
    assert reject.json()["status"] == "cancelled"


def test_api_disabled(monkeypatch, exec_db):
    monkeypatch.setenv("JARVIS_ENABLED", "false")
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", exec_db)
    app = FastAPI()
    app.include_router(jarvis_router)
    client = TestClient(app)
    resp = client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "inspect health", "dry_run": True},
    )
    assert resp.status_code == 403


def test_demo_task_websocket(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "Find websocket implementation", "dry_run": True},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_demo_task_containers(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "Inspect running containers", "dry_run": True},
    )
    assert resp.status_code == 200
    assert len(resp.json().get("artifacts") or []) >= 1


# --- artifacts (2 tests) ---


def test_artifact_storage(exec_db, monkeypatch, tmp_path):
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    from app.jarvis.artifacts.storage import create_artifact

    record = create_artifact(task_id="t1", name="report", content="# hello", fmt="markdown")
    assert record["task_id"] == "t1"
    assert record["format"] == "markdown"


def test_artifact_json_format(exec_db, monkeypatch, tmp_path):
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    from app.jarvis.artifacts.storage import create_artifact

    record = create_artifact(task_id="t2", name="data", content={"a": 1}, fmt="json")
    assert record["format"] == "json"


# --- audit (1 test) ---


def test_audit_log_written(exec_db):
    log_id = audit_mod.log_execution_event(
        task_id="audit-task",
        agent="test",
        tool="inspect_health",
        input_summary="in",
        output_summary="out",
        duration_ms=12,
    )
    assert log_id
    rows = audit_mod.list_execution_log("audit-task")
    assert len(rows) == 1
    assert rows[0]["agent"] == "test"
