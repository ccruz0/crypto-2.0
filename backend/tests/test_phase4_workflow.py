"""Tests for Jarvis Phase 4 change workflow."""

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
from app.jarvis.execution.change_service import (
    approve_change_task,
    list_approval_queue,
    reject_change_task,
    submit_change_task,
    update_change_patch,
)
from app.jarvis.execution.lifecycle import (
    CHANGE_WORKFLOW_PIPELINE,
    InvalidTaskTransitionError,
    TaskLifecycleState,
    validate_transition,
)
from app.jarvis.execution.safety import SafetyLevel, classify_phase4_action
from app.jarvis.github.integration import github_readonly_summary, inspect_branches, inspect_recent_commits
from app.jarvis.artifacts.storage import PHASE4_ARTIFACT_NAMES


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


# --- lifecycle Phase 4 (15 tests) ---


@pytest.mark.parametrize(
    "current,target",
    [
        ("planning", "investigating"),
        ("investigating", "patch_ready"),
        ("patch_ready", "reviewing"),
        ("reviewing", "testing"),
        ("testing", "waiting_for_approval"),
        ("waiting_for_approval", "approved"),
        ("approved", "completed"),
    ],
)
def test_phase4_valid_transitions(current, target):
    assert validate_transition(current, target).value == target


@pytest.mark.parametrize(
    "current,target",
    [
        ("investigating", "completed"),
        ("patch_ready", "approved"),
        ("reviewing", "executing"),
        ("approved", "investigating"),
    ],
)
def test_phase4_invalid_transitions(current, target):
    with pytest.raises(InvalidTaskTransitionError):
        validate_transition(current, target)


def test_change_workflow_pipeline_order():
    assert TaskLifecycleState.QUEUED in CHANGE_WORKFLOW_PIPELINE
    assert TaskLifecycleState.COMPLETED == CHANGE_WORKFLOW_PIPELINE[-1]


def test_phase4_states_exist():
    for state in ("investigating", "patch_ready", "reviewing", "testing", "approved"):
        assert TaskLifecycleState(state)


# --- change service (12 tests) ---


def test_submit_change_task_waiting_approval(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="Generate patch to improve deploy validation", dry_run=True, run_tests=False)
    assert detail["status"] == TaskLifecycleState.WAITING_FOR_APPROVAL.value
    assert detail["workflow_type"] == "phase4_change"
    assert detail["approval_required"] is True


def test_submit_change_creates_artifacts(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="Explain deployment pipeline", dry_run=True, run_tests=False)
    names = {a.get("standard_name") for a in detail.get("artifacts") or []}
    assert "patch.diff" in names
    assert "review.md" in names
    assert "tests.json" in names
    assert "repository_report.json" in names


def test_submit_change_audit_log(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="Identify dead code", dry_run=True, run_tests=False)
    agents = {e["agent"] for e in detail.get("execution_log") or []}
    assert "patch_agent" in agents
    assert "reviewer_agent" in agents


def test_submit_forbidden_fails(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="execute trade order now", dry_run=True)
    assert detail["status"] == TaskLifecycleState.FAILED.value


def test_approve_change_no_patch_apply(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="Review patch risk", dry_run=True, run_tests=False)
    approved = approve_change_task(detail["task_id"], actor_id="tester")
    assert approved["status"] == TaskLifecycleState.COMPLETED.value
    assert "NOT applied" in approved.get("final_answer", "")


def test_reject_change_task(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="Analyze websocket implementation", dry_run=True, run_tests=False)
    rejected = reject_change_task(detail["task_id"], actor_id="tester", comment="no")
    assert rejected["status"] == TaskLifecycleState.CANCELLED.value


def test_approval_queue_lists_pending(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    submit_change_task(objective="Find why OpenClaw regression happened", dry_run=True, run_tests=False)
    queue = list_approval_queue()
    assert len(queue) >= 1
    assert queue[0]["workflow_type"] == "phase4_change"


def test_update_change_patch_revision(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="patch update test", dry_run=True, run_tests=False)
    updated = update_change_patch(detail["task_id"], notes="revision 2")
    versions = [a.get("version", 1) for a in updated.get("artifacts") or [] if a.get("standard_name") == "patch.diff"]
    assert max(versions) >= 2


def test_submit_disabled_raises(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "false")
    with pytest.raises(RuntimeError):
        submit_change_task(objective="test", dry_run=True)


def test_review_stored_on_task(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="Review patch risk", dry_run=True, run_tests=False)
    review = detail.get("review") or {}
    assert "risk_score" in review
    assert "approval_recommendation" in review


# --- API routes (8 tests) ---


def test_api_change_submit(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Generate patch to improve deploy validation", "dry_run": True, "run_tests": False},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "waiting_for_approval"


def test_api_approval_queue(jarvis_client):
    jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Explain deployment pipeline", "dry_run": True, "run_tests": False},
    )
    resp = jarvis_client.get("/api/jarvis/approval-queue")
    assert resp.status_code == 200
    assert len(resp.json()["items"]) >= 1


def test_api_change_approve(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Review patch risk", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(f"/api/jarvis/tasks/change/{task_id}/approve", json={"actor_id": "tester"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_api_change_reject(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Identify dead code", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(f"/api/jarvis/tasks/change/{task_id}/reject", json={"actor_id": "tester"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


def test_api_repository_graph(jarvis_client):
    resp = jarvis_client.get("/api/jarvis/repository/graph?refresh=true")
    assert resp.status_code == 200
    assert "graph" in resp.json()


def test_api_github_readonly(jarvis_client):
    resp = jarvis_client.get("/api/jarvis/github/readonly")
    assert resp.status_code == 200
    body = resp.json()
    assert body["write_access"] is False
    assert body["merge"] is False


def test_api_change_detail(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Analyze websocket implementation", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.get(f"/api/jarvis/tasks/change/{task_id}")
    assert resp.status_code == 200
    assert resp.json()["workflow_type"] == "phase4_change"


def test_api_patch_revision(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "patch rev", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(f"/api/jarvis/tasks/change/{task_id}/patch", json={"notes": "v2"})
    assert resp.status_code == 200


# --- demo tasks (7 tests) ---


@pytest.mark.parametrize(
    "objective",
    [
        "Find why OpenClaw regression happened",
        "Explain deployment pipeline",
        "Identify dead code",
        "Generate patch to improve deploy validation",
        "Review patch risk",
        "Determine tests affected by routes_jarvis.py",
        "Analyze websocket implementation",
    ],
)
def test_demo_tasks_complete_lifecycle(exec_db, monkeypatch, objective):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective=objective, dry_run=True, run_tests=False)
    assert detail["status"] == TaskLifecycleState.WAITING_FOR_APPROVAL.value
    assert len(detail.get("artifacts") or []) >= 4
    assert len(detail.get("execution_log") or []) >= 3
    approved = approve_change_task(detail["task_id"], actor_id="demo")
    assert approved["status"] == TaskLifecycleState.COMPLETED.value


# --- safety Phase 4 (8 tests) ---


@pytest.mark.parametrize(
    "action,level",
    [
        ("patch_generation", SafetyLevel.SAFE_AUTO),
        ("patch_application", SafetyLevel.NEEDS_APPROVAL),
        ("pr_creation", SafetyLevel.NEEDS_APPROVAL),
        ("merge", SafetyLevel.FORBIDDEN),
        ("deploy", SafetyLevel.FORBIDDEN),
        ("trading", SafetyLevel.FORBIDDEN),
        ("secrets_access", SafetyLevel.FORBIDDEN),
        ("github_read", SafetyLevel.SAFE_AUTO),
    ],
)
def test_phase4_safety_actions(action, level):
    assert classify_phase4_action(action) == level


# --- github read-only (4 tests) ---


def test_github_readonly_summary():
    summary = github_readonly_summary()
    assert summary["write_access"] is False
    assert summary["pr_creation"] is False


def test_inspect_branches():
    result = inspect_branches()
    assert result["read_only"] is True
    assert "branches" in result


def test_inspect_commits():
    result = inspect_recent_commits(limit=5)
    assert result["read_only"] is True
    assert "commits" in result


# --- artifacts (2 tests) ---


def test_phase4_artifact_names():
    assert "patch.diff" in PHASE4_ARTIFACT_NAMES
    assert "review.md" in PHASE4_ARTIFACT_NAMES
    assert "tests.json" in PHASE4_ARTIFACT_NAMES
    assert "repository_report.json" in PHASE4_ARTIFACT_NAMES


# --- final safety review (6 tests) ---


def test_no_patch_application_on_approve(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = submit_change_task(objective="safe patch", dry_run=True, run_tests=False)
    approved = approve_change_task(detail["task_id"])
    assert "NOT applied" in approved["final_answer"]


def test_phase3_still_works(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "Inspect deployment health", "dry_run": True},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "completed"


def test_phase3_approval_preserved(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "restart backend", "approval_mode": "manual", "dry_run": True},
    )
    assert resp.json()["status"] == "waiting_for_approval"
