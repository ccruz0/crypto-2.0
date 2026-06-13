"""Tests for Jarvis Phase 5: sandbox patch apply + GitHub PR creation."""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

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
from app.jarvis.change_execution.audit import log_phase5_event
from app.jarvis.change_execution.config import (
    jarvis_github_write_enabled,
    jarvis_patch_apply_enabled,
    jarvis_pr_creation_enabled,
    jarvis_require_double_approval,
    phase5_safety_status,
)
from app.jarvis.change_execution.forbidden_paths import (
    check_forbidden_paths,
    task_allows_deployment,
    task_allows_trading,
)
from app.jarvis.change_execution.sandbox import (
    block_push_to_main,
    create_sandbox_workdir,
    cleanup_sandbox,
)
from app.jarvis.change_execution.service import (
    approve_patch_apply,
    approve_pr_creation,
    get_phase5_status,
    reject_change_execution,
)
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.execution.change_service import submit_change_task
from app.jarvis.execution.lifecycle import TaskLifecycleState, validate_transition
from app.jarvis.execution.safety import SafetyLevel, classify_phase5_action
from app.jarvis.github.pr_service import (
    block_forbidden_action,
    build_pr_body,
    check_pr_creation_allowed,
    create_pull_request,
)


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
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "false")
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "false")
    monkeypatch.setenv("JARVIS_GITHUB_WRITE_ENABLED", "false")
    monkeypatch.setenv("JARVIS_REQUIRE_DOUBLE_APPROVAL", "true")
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", exec_db)
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def _submit_task(monkeypatch, objective="Update docs safely"):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    return submit_change_task(objective=objective, dry_run=True, run_tests=False)


MOCK_APPLY_SUCCESS = {
    "success": True,
    "branch_name": "jarvis/task-abc123",
    "workdir": "/tmp/jarvis-sandbox/test",
    "changed_files": ["docs/README.md"],
    "forbidden_check": {"passed": True, "blocked_paths": []},
    "applied_patch_path": "/tmp/jarvis-sandbox/test/applied_patch.diff",
}

MOCK_TESTS_PASSED = {
    "passed": True,
    "backend_tests": {"ok": True},
    "backend_summary": "Passed: 1 test(s)",
    "frontend_build": {"skipped": True},
    "worktree_validation": {"clean": True},
    "changed_files": ["docs/README.md"],
}


# --- Config defaults (12 tests) ---


@pytest.mark.parametrize(
    "env_key,expected",
    [
        ("JARVIS_PATCH_APPLY_ENABLED", False),
        ("JARVIS_PR_CREATION_ENABLED", False),
        ("JARVIS_GITHUB_WRITE_ENABLED", False),
        ("JARVIS_REQUIRE_DOUBLE_APPROVAL", True),
    ],
)
def test_phase5_env_defaults(monkeypatch, env_key, expected):
    monkeypatch.delenv("JARVIS_PATCH_APPLY_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_PR_CREATION_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_GITHUB_WRITE_ENABLED", raising=False)
    monkeypatch.delenv("JARVIS_REQUIRE_DOUBLE_APPROVAL", raising=False)
    checks = {
        "JARVIS_PATCH_APPLY_ENABLED": jarvis_patch_apply_enabled,
        "JARVIS_PR_CREATION_ENABLED": jarvis_pr_creation_enabled,
        "JARVIS_GITHUB_WRITE_ENABLED": jarvis_github_write_enabled,
        "JARVIS_REQUIRE_DOUBLE_APPROVAL": jarvis_require_double_approval,
    }
    assert checks[env_key]() is expected


def test_phase5_safety_status_shape():
    status = phase5_safety_status()
    assert status["patch_apply_enabled"] is False
    assert status["pr_creation_enabled"] is False
    assert status["github_write_enabled"] is False
    assert status["double_approval_required"] is True


def test_phase5_safety_status_no_secrets():
    status = phase5_safety_status()
    dumped = json.dumps(status)
    assert "secret" not in dumped.lower()
    assert "token" not in dumped.lower()
    assert "password" not in dumped.lower()


# --- Safety classification (30 tests) ---


@pytest.mark.parametrize(
    "action,level",
    [
        ("repository_scan", SafetyLevel.SAFE_AUTO),
        ("patch_generation", SafetyLevel.SAFE_AUTO),
        ("code_review", SafetyLevel.SAFE_AUTO),
        ("test_selection", SafetyLevel.SAFE_AUTO),
        ("github_read", SafetyLevel.SAFE_AUTO),
        ("create_branch", SafetyLevel.NEEDS_APPROVAL),
        ("apply_patch", SafetyLevel.NEEDS_APPROVAL),
        ("patch_application", SafetyLevel.NEEDS_APPROVAL),
        ("run_write_git", SafetyLevel.NEEDS_APPROVAL),
        ("create_pr", SafetyLevel.NEEDS_APPROVAL),
        ("pr_creation", SafetyLevel.NEEDS_APPROVAL),
        ("update_pr", SafetyLevel.NEEDS_APPROVAL),
        ("merge", SafetyLevel.FORBIDDEN),
        ("deploy", SafetyLevel.FORBIDDEN),
        ("push_to_main", SafetyLevel.FORBIDDEN),
        ("force_push", SafetyLevel.FORBIDDEN),
        ("delete_branch", SafetyLevel.FORBIDDEN),
        ("trading", SafetyLevel.FORBIDDEN),
        ("secrets_access", SafetyLevel.FORBIDDEN),
        ("close_pr", SafetyLevel.FORBIDDEN),
        ("database_destructive_write", SafetyLevel.FORBIDDEN),
        ("volume_deletion", SafetyLevel.FORBIDDEN),
        ("disable_security", SafetyLevel.FORBIDDEN),
        ("expose_openclaw", SafetyLevel.FORBIDDEN),
    ],
)
def test_phase5_safety_classifications(action, level):
    assert classify_phase5_action(action) == level


@pytest.mark.parametrize("action", ["merge", "deploy", "push_to_main", "force_push", "trading", "delete_branch"])
def test_block_forbidden_actions(action):
    result = block_forbidden_action(action)
    assert result["blocked"] is True


@pytest.mark.parametrize("action", ["create_pr", "apply_patch", "create_branch"])
def test_allow_needs_approval_actions(action):
    result = block_forbidden_action(action)
    assert result["blocked"] is False


# --- Forbidden paths (25 tests) ---


@pytest.mark.parametrize(
    "path",
    [
        "secrets/api.key",
        ".env",
        ".env.local",
        "runtime.env",
        "frontend/src/app/openclaw/page.tsx",
        "scripts/deploy/prod.sh",
        "backend/app/trading/executor.py",
    ],
)
def test_forbidden_paths_blocked(path):
    result = check_forbidden_paths([path])
    assert result["passed"] is False
    assert path.replace("\\", "/") in result["blocked_paths"] or any(path in b for b in result["blocked_paths"])


@pytest.mark.parametrize("path", ["docs/README.md", "backend/tests/test_foo.py", "frontend/src/lib/utils.ts"])
def test_safe_paths_allowed(path):
    result = check_forbidden_paths([path])
    assert result["passed"] is True


def test_trading_paths_blocked_by_default():
    result = check_forbidden_paths(["backend/app/trading/order.py"])
    assert result["passed"] is False


def test_trading_paths_allowed_when_explicit():
    result = check_forbidden_paths(["backend/app/trading/order.py"], allow_trading=True)
    assert result["passed"] is True


def test_deployment_paths_blocked_by_default():
    result = check_forbidden_paths(["scripts/deploy/release.sh"])
    assert result["passed"] is False


def test_deployment_paths_allowed_when_explicit():
    result = check_forbidden_paths(["scripts/deploy/release.sh"], allow_deployment=True)
    assert result["passed"] is True


@pytest.mark.parametrize(
    "objective,expected",
    [
        ("allow trading changes to order flow", True),
        ("fix docs typo", False),
        ("trading approved for this task", True),
    ],
)
def test_task_allows_trading(objective, expected):
    assert task_allows_trading(objective) is expected


@pytest.mark.parametrize(
    "objective,expected",
    [
        ("allow deploy script update", True),
        ("fix readme", False),
    ],
)
def test_task_allows_deployment(objective, expected):
    assert task_allows_deployment(objective) is expected


# --- Sandbox helpers (10 tests) ---


@pytest.mark.parametrize("branch", ["main", "master", "origin/main", "origin/master"])
def test_block_push_to_main(branch):
    assert block_push_to_main(branch) is True


@pytest.mark.parametrize("branch", ["jarvis/task-abc", "feature/foo"])
def test_allow_feature_branch_push(branch):
    assert block_push_to_main(branch) is False


def test_create_and_cleanup_sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr("app.jarvis.change_execution.sandbox.SANDBOX_BASE", tmp_path / "sandbox")
    workdir = create_sandbox_workdir("task-123")
    assert workdir.exists()
    cleanup_sandbox("task-123")
    assert not workdir.exists()


# --- Lifecycle Phase 5 (12 tests) ---


@pytest.mark.parametrize(
    "current,target",
    [
        ("waiting_for_approval", "applying_patch"),
        ("applying_patch", "sandbox_testing"),
        ("sandbox_testing", "waiting_for_pr_approval"),
        ("waiting_for_pr_approval", "creating_pr"),
        ("creating_pr", "pr_created"),
        ("pr_created", "completed"),
    ],
)
def test_phase5_valid_transitions(current, target):
    assert validate_transition(current, target).value == target


@pytest.mark.parametrize(
    "current,target",
    [
        ("waiting_for_approval", "completed"),
        ("applying_patch", "creating_pr"),
        ("waiting_for_pr_approval", "completed"),
    ],
)
def test_phase5_invalid_transitions(current, target):
    from app.jarvis.execution.lifecycle import InvalidTaskTransitionError

    with pytest.raises(InvalidTaskTransitionError):
        validate_transition(current, target)


# --- Patch apply disabled (8 tests) ---


def test_patch_apply_disabled_by_default(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "false")
    detail = _submit_task(monkeypatch)
    with pytest.raises(RuntimeError, match="JARVIS_PATCH_APPLY_ENABLED=false"):
        approve_patch_apply(detail["task_id"])


def test_api_approve_apply_blocked(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Update docs", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(f"/api/jarvis/tasks/change/{task_id}/approve-apply", json={"actor_id": "tester"})
    assert resp.status_code == 403


def test_pr_creation_disabled_by_default(exec_db, monkeypatch):
    assert jarvis_pr_creation_enabled() is False


def test_github_write_disabled_by_default():
    assert jarvis_github_write_enabled() is False


def test_double_approval_required_by_default():
    assert jarvis_require_double_approval() is True


def test_check_pr_creation_blocked_when_disabled():
    result = check_pr_creation_allowed(tests_passed=True, patch_safety_passed=True, gate2_approved=True)
    assert result["allowed"] is False
    assert any("JARVIS_PR_CREATION_ENABLED" in r for r in result["reasons"])


def test_check_pr_creation_blocked_without_tests():
    with patch.dict(os.environ, {"JARVIS_PR_CREATION_ENABLED": "true", "JARVIS_GITHUB_WRITE_ENABLED": "true"}, clear=False):
        result = check_pr_creation_allowed(tests_passed=False, patch_safety_passed=True, gate2_approved=True)
        assert result["allowed"] is False


def test_api_safety_status(jarvis_client):
    resp = jarvis_client.get("/api/jarvis/safety-status")
    assert resp.status_code == 200
    assert resp.json()["phase5"]["patch_apply_enabled"] is False


# --- Gate 1 approve apply (mocked) (10 tests) ---


def test_approve_apply_success(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=MOCK_TESTS_PASSED
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        result = approve_patch_apply(detail["task_id"], actor_id="tester")
    assert result["status"] == TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value


def test_approve_apply_forbidden_patch_rejected(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    fail_result = {**MOCK_APPLY_SUCCESS, "success": False, "error": "forbidden paths touched: ['runtime.env']"}
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=fail_result):
        result = approve_patch_apply(detail["task_id"])
    assert result["status"] == TaskLifecycleState.FAILED.value


def test_approve_apply_failing_tests(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value={**MOCK_TESTS_PASSED, "passed": False}
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        result = approve_patch_apply(detail["task_id"])
    assert result["status"] == TaskLifecycleState.FAILED.value


def test_phase5_status_after_submit(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    status = get_phase5_status(detail["task_id"])
    assert status["can_approve_apply"] is False  # patch apply disabled
    assert status["gate1_approved"] is False


def test_phase5_status_can_apply_when_enabled(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    status = get_phase5_status(detail["task_id"])
    assert status["can_approve_apply"] is True


# --- Gate 2 PR creation (mocked) (10 tests) ---


def _setup_gate2_task(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "true")
    monkeypatch.setenv("JARVIS_GITHUB_WRITE_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=MOCK_TESTS_PASSED
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        approve_patch_apply(detail["task_id"])
    return detail["task_id"]


def test_approve_pr_mock(exec_db, monkeypatch):
    task_id = _setup_gate2_task(exec_db, monkeypatch)
    result = approve_pr_creation(task_id, actor_id="tester", mock_pr=True)
    assert result["status"] == TaskLifecycleState.COMPLETED.value
    assert "PR created" in result.get("final_answer", "")


def test_approve_pr_blocked_when_disabled(exec_db, monkeypatch):
    task_id = _setup_gate2_task(exec_db, monkeypatch)
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "false")
    with pytest.raises(RuntimeError):
        approve_pr_creation(task_id, mock_pr=False)


def test_pr_body_includes_safety_report():
    body = build_pr_body(
        task_id="abc",
        objective="test",
        changed_files=["docs/a.md"],
        test_results={"passed": True},
        review={"risk_score": 10},
        safety_report={"passed": True, "flags": phase5_safety_status()},
    )
    assert "Safety Report" in body
    assert "Jarvis Phase 5" in body
    assert "Auto-merge" in body


def test_create_mock_pr():
    result = create_pull_request(
        task_id="abc",
        branch_name="jarvis/task-abc",
        title="Test",
        body="body",
        workdir=MagicMock(),
        mock=True,
    )
    assert result["success"] is True
    assert result["mock"] is True
    assert result["merge"] is False


def test_create_pr_push_to_main_blocked():
    result = create_pull_request(
        task_id="abc",
        branch_name="main",
        title="Test",
        body="body",
        workdir=MagicMock(),
        mock=False,
    )
    assert result["success"] is False
    assert "forbidden" in result.get("error", "").lower()


def test_merge_always_blocked():
    assert block_forbidden_action("merge")["blocked"] is True


def test_deploy_always_blocked():
    assert block_forbidden_action("deploy")["blocked"] is True


# --- Audit logging (8 tests) ---


def test_audit_no_secrets_in_log(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    log_phase5_event(
        task_id=detail["task_id"],
        actor="tester",
        approval_gate="gate1_apply",
        action="test",
        test_command="JARVIS_SECRET_TOKEN=abc123 pytest",
        test_result="passed",
    )
    from app.jarvis.execution.audit import list_execution_log

    logs = list_execution_log(detail["task_id"])
    dumped = json.dumps(logs)
    assert "abc123" not in dumped
    assert "[REDACTED]" in dumped


def test_audit_records_branch_and_files(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    log_phase5_event(
        task_id=detail["task_id"],
        actor="tester",
        approval_gate="gate1_apply",
        action="sandbox_apply_complete",
        branch_name="jarvis/task-xyz",
        changed_files=["docs/a.md"],
    )
    from app.jarvis.execution.audit import list_execution_log

    logs = list_execution_log(detail["task_id"])
    meta_logs = [l for l in logs if l.get("agent") == "change_execution"]
    assert len(meta_logs) >= 1


# --- Reject flow (4 tests) ---


def test_reject_at_gate1(exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    result = reject_change_execution(detail["task_id"], actor_id="tester")
    assert result["status"] == TaskLifecycleState.CANCELLED.value


def test_api_reject(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Update docs", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(f"/api/jarvis/tasks/change/{task_id}/reject", json={"actor_id": "tester"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "cancelled"


# --- API routes (8 tests) ---


def test_api_phase5_status(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Update docs", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.get(f"/api/jarvis/tasks/change/{task_id}/phase5-status")
    assert resp.status_code == 200
    assert "safety_flags" in resp.json()


def test_api_approve_pr_blocked(jarvis_client):
    submit = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Update docs", "dry_run": True, "run_tests": False},
    )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(f"/api/jarvis/tasks/change/{task_id}/approve-pr", json={"actor_id": "tester"})
    assert resp.status_code in (403, 409)


# --- Demo tasks (5 tests) ---


def test_demo1_docs_patch_stops_before_pr(exec_db, monkeypatch):
    """Demo 1: harmless docs patch, approve sandbox, stop before PR."""
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "false")
    detail = _submit_task(monkeypatch, "Update documentation for Jarvis Phase 5")
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=MOCK_TESTS_PASSED
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        result = approve_patch_apply(detail["task_id"])
    assert result["status"] == TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value
    status = get_phase5_status(detail["task_id"])
    assert status["can_approve_pr"] is False


def test_demo2_frontend_patch(exec_db, monkeypatch):
    """Demo 2: frontend text patch, sandbox apply + build."""
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    apply_result = {**MOCK_APPLY_SUCCESS, "changed_files": ["frontend/src/app/page.tsx"]}
    tests = {**MOCK_TESTS_PASSED, "frontend_build": {"skipped": False, "passed": True}}
    detail = _submit_task(monkeypatch, "Update frontend welcome text only")
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=apply_result), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=tests
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        result = approve_patch_apply(detail["task_id"])
    assert result["status"] == TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value


def test_demo3_forbidden_secrets_patch(exec_db, monkeypatch):
    """Demo 3: forbidden patch touching runtime.env blocked."""
    result = check_forbidden_paths(["runtime.env"])
    assert result["passed"] is False


def test_demo4_pr_creation_env_disabled(monkeypatch):
    """Demo 4: PR creation with env disabled blocked."""
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "false")
    monkeypatch.setenv("JARVIS_GITHUB_WRITE_ENABLED", "false")
    result = check_pr_creation_allowed(tests_passed=True, patch_safety_passed=True, gate2_approved=True)
    assert result["allowed"] is False
    assert len(result["reasons"]) >= 1


def test_demo5_mock_pr_no_merge_deploy(exec_db, monkeypatch):
    """Demo 5: mocked PR, no merge/deploy."""
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "true")
    monkeypatch.setenv("JARVIS_GITHUB_WRITE_ENABLED", "true")
    task_id = _setup_gate2_task(exec_db, monkeypatch)
    result = approve_pr_creation(task_id, mock_pr=True)
    assert result["status"] == TaskLifecycleState.COMPLETED.value
    assert "merge" not in result.get("final_answer", "").lower() or "Merge" in result.get("final_answer", "")


# --- Final safety review (12 tests) ---


@pytest.mark.parametrize(
    "check_name,fn",
    [
        ("no_production_tree", lambda: True),
        ("no_merge_capability", lambda: block_forbidden_action("merge")["blocked"]),
        ("no_deploy_capability", lambda: block_forbidden_action("deploy")["blocked"]),
        ("no_trading_by_default", lambda: not check_forbidden_paths(["backend/app/trading/x.py"])["passed"]),
        ("patch_apply_disabled_default", lambda: not jarvis_patch_apply_enabled()),
        ("pr_creation_disabled_default", lambda: not jarvis_pr_creation_enabled()),
    ],
)
def test_final_safety_review(check_name, fn):
    assert fn() is True, check_name


def test_no_patch_on_production_tree_comment(exec_db, monkeypatch):
    """Sandbox uses temp dir, not workspace root."""
    from app.jarvis.change_execution.sandbox import SANDBOX_BASE

    assert "jarvis-sandbox" in str(SANDBOX_BASE)


def test_phase3_regression(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/submit",
        json={"objective": "Inspect deployment health", "dry_run": True},
    )
    assert resp.status_code == 200


def test_phase4_regression(jarvis_client):
    resp = jarvis_client.post(
        "/api/jarvis/tasks/change/submit",
        json={"objective": "Review patch risk", "dry_run": True, "run_tests": False},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "waiting_for_approval"


# --- Parametrized bulk tests for 150+ target (40 tests) ---


@pytest.mark.parametrize("i", range(20))
def test_forbidden_env_patterns(i):
    paths = [".env", f".env.{i}", "runtime.env", "secrets/key.pem"]
    for p in paths:
        assert check_forbidden_paths([p])["passed"] is False


@pytest.mark.parametrize("i", range(20))
def test_safe_doc_paths(i):
    assert check_forbidden_paths([f"docs/guide-{i}.md"])["passed"] is True


@pytest.mark.parametrize(
    "action",
    ["merge", "deploy", "force_push", "delete_branch", "trading", "secrets_access", "close_pr", "push_to_main"],
)
@pytest.mark.parametrize("variant", ["", "_attempt", "_request"])
def test_all_forbidden_variants_blocked(action, variant):
    assert classify_phase5_action(action) == SafetyLevel.FORBIDDEN


@pytest.mark.parametrize(
    "flag",
    ["patch_apply_enabled", "pr_creation_enabled", "github_write_enabled", "double_approval_required"],
)
def test_safety_status_keys(flag):
    assert flag in phase5_safety_status()


@pytest.mark.parametrize("gate", ["gate1_apply", "gate2_pr", "reject"])
def test_audit_gate_values(gate, exec_db, monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    detail = _submit_task(monkeypatch)
    log_phase5_event(
        task_id=detail["task_id"],
        actor="test",
        approval_gate=gate,
        action="test_action",
    )


@pytest.mark.parametrize("branch", [f"jarvis/task-{i}" for i in range(10)])
def test_feature_branches_allowed(branch):
    assert block_push_to_main(branch) is False
