"""Tests for Jarvis Autonomous Coding Workflow (ACW) — LAB only."""

from __future__ import annotations

import json
import subprocess
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
from app.jarvis.change_execution.service import approve_patch_apply, approve_pr_creation, get_phase5_status
from app.jarvis.coding_workflow.acw_bugfix_fixtures import ACW_BF_001_OBJECTIVE
from app.jarvis.coding_workflow.evidence import collect_acw_evidence, evidence_summary
from app.jarvis.coding_workflow.patch_bridge import (
    PlaceholderPatchError,
    build_acw_prompt,
    build_acw_retry_prompt,
    generate_patch_via_bridge,
    validate_patch_diff,
)
from app.jarvis.coding_workflow.schemas import WORKFLOW_TYPE
from app.jarvis.coding_workflow.service import submit_coding_workflow
from app.jarvis.execution import audit as audit_mod
from app.jarvis.execution import persistence as persist_mod
from app.jarvis.execution.change_service import approve_change_task
from app.jarvis.execution.lifecycle import TaskLifecycleState, validate_transition
from app.jarvis.execution.persistence import get_execution_task

REAL_DIFF = """--- a/docs/acw_test.md
+++ b/docs/acw_test.md
@@ -1,2 +1,5 @@
 # ACW test doc
+Added line for ACW validation.
+Second substantive change.
"""

COMMENT_ONLY_DIFF = """--- a/backend/foo.py
+++ b/backend/foo.py
@@ -1 +1,2 @@
 x = 1
+# comment-only addition
"""

ACW_BF_001_COMMENT_ONLY_DIFF = """--- a/frontend/src/app/page.tsx
+++ b/frontend/src/app/page.tsx
@@ -4643,6 +4643,7 @@
         {/* Header */}
         <div className="mb-4 flex justify-between items-center">
+# ACW-BF-001: rename dashboard title — comment-only stub
           <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Trading Dashboard</h1>
"""

ACW_BF_001_SUBSTANTIVE_DIFF = """--- a/frontend/src/app/page.tsx
+++ b/frontend/src/app/page.tsx
@@ -4643,7 +4643,7 @@
         {/* Header */}
         <div className="mb-4 flex justify-between items-center">
-          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Trading Dashboard</h1>
+          <h1 className="text-2xl font-bold text-gray-900 dark:text-white">Crypto Trading Dashboard</h1>
           <button
"""

SUBSTANTIVE_CODE_DIFF = """--- a/backend/foo.py
+++ b/backend/foo.py
@@ -1 +1,2 @@
 x = 1
+x = 2
"""

MOCK_PATCH = {
    "patch_id": "patch-acw-1",
    "objective": "Update docs safely for ACW",
    "target_files": ["docs/acw_test.md"],
    "unified_diff": REAL_DIFF,
    "patch_summary": "Cursor bridge patch: 1 file(s)",
    "revision": 1,
    "content_hash": "abc123",
    "source": "cursor_bridge",
    "risk_assessment": {"risk_score": 25, "risk_level": "low", "factors": []},
    "estimated_impact": {"auto_apply": False, "files_count": 1},
}

MOCK_APPLY_SUCCESS = {
    "success": True,
    "branch_name": "jarvis/acw-test",
    "workdir": "/tmp/jarvis-sandbox/acw",
    "changed_files": ["docs/acw_test.md"],
    "forbidden_check": {"passed": True, "blocked_paths": []},
    "applied_patch_path": "/tmp/jarvis-sandbox/acw/applied_patch.diff",
}

MOCK_TESTS_PASSED = {
    "passed": True,
    "backend_tests": {"ok": True},
    "backend_summary": "Passed: 1 test(s)",
    "frontend_build": {"skipped": True},
    "worktree_validation": {"clean": True},
    "changed_files": ["docs/acw_test.md"],
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
def acw_env(monkeypatch):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("ATP_TRADING_ONLY", "0")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.setenv("CURSOR_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("CURSOR_API_KEY", "test-lab-cursor-key")
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "true")
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "true")
    monkeypatch.setenv("JARVIS_GITHUB_WRITE_ENABLED", "true")
    monkeypatch.setenv("JARVIS_REQUIRE_DOUBLE_APPROVAL", "true")


@pytest.fixture()
def jarvis_client(exec_db, monkeypatch, tmp_path, acw_env):
    import app.database as db_mod

    monkeypatch.setattr(db_mod, "engine", exec_db)
    from app.jarvis import artifacts as artifacts_pkg

    monkeypatch.setattr(artifacts_pkg.storage, "_ARTIFACTS_DIR", tmp_path)
    app = FastAPI()
    app.include_router(jarvis_router)
    return TestClient(app)


def _submit_acw(monkeypatch, objective="Update docs safely for ACW test"):
    monkeypatch.setenv("JARVIS_ENABLED", "true")
    monkeypatch.setenv("ATP_TRADING_ONLY", "0")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.setenv("CURSOR_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("CURSOR_API_KEY", "test-lab-cursor-key")
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=MOCK_PATCH):
        return submit_coding_workflow(objective=objective)


def test_acw_blocks_when_cursor_auth_missing(exec_db, monkeypatch, acw_env):
    monkeypatch.delenv("CURSOR_API_KEY", raising=False)
    from app.jarvis.coding_workflow.service import check_acw_submit_allowed
    from app.services.cursor_execution_bridge import CURSOR_AUTH_MISSING_ERROR, CursorAuthMissingError

    with patch("app.services.cursor_execution_bridge.is_cursor_agent_logged_in", return_value=False):
        with pytest.raises(CursorAuthMissingError) as exc:
            check_acw_submit_allowed()
        assert exc.value.error_info == CURSOR_AUTH_MISSING_ERROR


def test_acw_submit_happy_path(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    assert detail["status"] == TaskLifecycleState.WAITING_FOR_APPROVAL.value
    assert detail["workflow_type"] == WORKFLOW_TYPE
    assert detail.get("approval_package", {}).get("workflow_type") == WORKFLOW_TYPE
    names = {a.get("standard_name") or a.get("name") for a in detail.get("artifacts", [])}
    assert "patch.diff" in names
    assert "evidence.json" in names
    assert "approval_package.json" in names


def test_acw_evidence_collection(exec_db, monkeypatch, acw_env):
    with patch("app.jarvis.coding_workflow.evidence.collect_evidence") as mock_collect:
        mock_collect.return_value = ([], [{"tool": "inspect_health", "ok": True, "summary": "ok"}], "health", "t1", None, [])
        evidence = collect_acw_evidence("Check deployment health for docs update")
    assert "repository_context" in evidence
    assert "safety_classification" in evidence
    assert "code_references" in evidence
    summary = evidence_summary(evidence)
    assert "safety_level" in summary


def test_acw_rejects_forbidden_objective(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch, objective="deploy to production immediately and delete all secrets")
    assert detail["status"] == TaskLifecycleState.FAILED.value


def test_acw_rejects_placeholder_patch(exec_db, monkeypatch, acw_env):
    with patch(
        "app.jarvis.coding_workflow.service.generate_patch_via_bridge",
        side_effect=PlaceholderPatchError("placeholder patch detected"),
    ):
        detail = submit_coding_workflow(objective="Update docs safely")
    assert detail["status"] == TaskLifecycleState.FAILED.value
    assert "Placeholder" in (detail.get("error") or "")


def test_acw_gate1_apply_disabled(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "false")
    with pytest.raises(RuntimeError):
        approve_patch_apply(detail["task_id"])


def test_acw_gate2_pr_disabled(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=MOCK_TESTS_PASSED
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        approve_patch_apply(detail["task_id"])
    monkeypatch.setenv("JARVIS_PR_CREATION_ENABLED", "false")
    with pytest.raises(RuntimeError):
        approve_pr_creation(detail["task_id"], mock_pr=False)


def test_acw_gate1_tests_fail(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value={**MOCK_TESTS_PASSED, "passed": False}
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        result = approve_patch_apply(detail["task_id"])
    assert result["status"] == TaskLifecycleState.FAILED.value


def test_acw_forbidden_paths_in_patch(exec_db, monkeypatch, acw_env):
    bad_patch = {
        **MOCK_PATCH,
        "target_files": ["secrets/runtime.env"],
        "unified_diff": """--- a/secrets/runtime.env
+++ b/secrets/runtime.env
@@ -1 +1,2 @@
+LEAK=true
""",
    }
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=bad_patch):
        detail = submit_coding_workflow(objective="Update docs safely")
    assert detail["status"] == TaskLifecycleState.FAILED.value


def test_acw_trading_only_refused(jarvis_client, monkeypatch):
    monkeypatch.setenv("ATP_TRADING_ONLY", "1")
    monkeypatch.setenv("JARVIS_BUILDER_ALLOWED", "1")
    monkeypatch.setenv("CURSOR_BRIDGE_ENABLED", "true")
    resp = jarvis_client.post(
        "/api/jarvis/coding-workflow/submit",
        json={"objective": "Update docs safely"},
    )
    assert resp.status_code == 403
    assert "ATP_TRADING_ONLY" in resp.json()["detail"]


def test_acw_approval_package_schema(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    pkg = detail.get("approval_package") or {}
    for key in (
        "objective",
        "task_id",
        "workflow_type",
        "plan",
        "evidence_summary",
        "patch_diff_summary",
        "full_patch_artifact",
        "risk_score",
        "forbidden_path_check",
        "required_approvals",
        "pr_creation_eligible",
    ):
        assert key in pkg, f"missing {key}"
    assert pkg["workflow_type"] == WORKFLOW_TYPE
    assert "gate1_apply" in pkg["required_approvals"]


def test_acw_lifecycle_transitions():
    assert validate_transition(
        TaskLifecycleState.WAITING_FOR_APPROVAL,
        TaskLifecycleState.APPLYING_PATCH,
    )
    assert validate_transition(
        TaskLifecycleState.SANDBOX_TESTING,
        TaskLifecycleState.WAITING_FOR_PR_APPROVAL,
    )
    assert validate_transition(TaskLifecycleState.CREATING_PR, TaskLifecycleState.PR_CREATED)
    assert validate_transition(TaskLifecycleState.PR_CREATED, TaskLifecycleState.COMPLETED)


def test_acw_blocks_legacy_approve(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    with pytest.raises(ValueError, match="Gate 1"):
        approve_change_task(detail["task_id"])


def test_acw_api_submit(jarvis_client):
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=MOCK_PATCH):
        resp = jarvis_client.post(
            "/api/jarvis/coding-workflow/submit",
            json={"objective": "Update docs safely for ACW API test"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["workflow_type"] == WORKFLOW_TYPE


def test_acw_api_gate1_disabled(jarvis_client, monkeypatch):
    monkeypatch.setenv("JARVIS_PATCH_APPLY_ENABLED", "false")
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=MOCK_PATCH):
        submit = jarvis_client.post(
            "/api/jarvis/coding-workflow/submit",
            json={"objective": "Update docs"},
        )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.post(
        f"/api/jarvis/coding-workflow/{task_id}/approve-apply",
        json={"actor_id": "tester"},
    )
    assert resp.status_code == 403


def test_validate_patch_rejects_placeholder():
    with pytest.raises(PlaceholderPatchError):
        validate_patch_diff("")
    with pytest.raises(PlaceholderPatchError):
        validate_patch_diff("+# TODO: implement validated change\n")
    with pytest.raises(PlaceholderPatchError):
        validate_patch_diff(
            "--- a/x\n+++ b/x\n@@ -1 +1,2 @@\n+# Jarvis Phase 4 proposed patch (NOT APPLIED)\n+# TODO: implement validated change\n"
        )
    with pytest.raises(PlaceholderPatchError):
        validate_patch_diff(COMMENT_ONLY_DIFF)


def test_build_acw_retry_prompt_requires_substantive_change():
    prompt = build_acw_retry_prompt(
        objective="Fix foo",
        plan={"steps": [{"description": "change x"}]},
        evidence={"code_references": ["backend/foo.py"]},
        target_files=["backend/foo.py"],
        rejection_reason="comment-only diff — no substantive code changes",
    )
    assert "RETRY" in prompt
    assert "real code change" in prompt.lower()
    assert "comment-only" in prompt.lower()
    assert "backend/foo.py" in prompt


def test_acw_bf_001_objective_includes_exact_file():
    assert "frontend/src/app/page.tsx" in ACW_BF_001_OBJECTIVE
    prompt = build_acw_prompt(
        objective=ACW_BF_001_OBJECTIVE,
        plan={"steps": [{"description": "Rename dashboard h1 title"}]},
        evidence={"code_references": ["frontend/src/app/page.tsx"]},
        target_files=["frontend/src/app/page.tsx"],
    )
    assert "frontend/src/app/page.tsx" in prompt


def test_acw_bf_001_objective_includes_exact_text_change():
    assert "Trading Dashboard" in ACW_BF_001_OBJECTIVE
    assert "Crypto Trading Dashboard" in ACW_BF_001_OBJECTIVE
    assert 'className="text-2xl font-bold text-gray-900 dark:text-white"' in ACW_BF_001_OBJECTIVE


def test_acw_bf_001_comment_only_diff_rejected_by_validation():
    with pytest.raises(PlaceholderPatchError, match="comment-only"):
        validate_patch_diff(ACW_BF_001_COMMENT_ONLY_DIFF)
    validate_patch_diff(ACW_BF_001_SUBSTANTIVE_DIFF)


def _patch_bridge_env(monkeypatch):
    monkeypatch.setenv("CURSOR_BRIDGE_ENABLED", "true")
    monkeypatch.setenv("CURSOR_API_KEY", "test-lab-cursor-key")


def test_generate_patch_retries_comment_only_then_succeeds(monkeypatch, tmp_path):
    _patch_bridge_env(monkeypatch)
    staging = tmp_path / "staging"
    staging.mkdir()
    attempt = {"n": 0}
    invoke_calls: list[str] = []

    def _mock_provision(task_id):
        return staging

    def _mock_invoke(_staging, prompt, task_id=""):
        invoke_calls.append(prompt)
        return {"success": True, "output": "ok"}

    def _mock_capture(_staging, task_id):
        attempt["n"] += 1
        diff_path = tmp_path / f"{task_id}-{attempt['n']}.diff"
        diff_path.write_text(
            COMMENT_ONLY_DIFF if attempt["n"] == 1 else SUBSTANTIVE_CODE_DIFF,
            encoding="utf-8",
        )
        return diff_path

    with patch("app.jarvis.coding_workflow.patch_bridge.provision_staging_workspace", side_effect=_mock_provision), patch(
        "app.jarvis.coding_workflow.patch_bridge.invoke_cursor_cli", side_effect=_mock_invoke
    ), patch("app.jarvis.coding_workflow.patch_bridge.capture_diff", side_effect=_mock_capture), patch(
        "app.jarvis.coding_workflow.patch_bridge.cleanup_staging"
    ), patch("app.jarvis.coding_workflow.patch_bridge._reset_staging_workspace") as reset_mock:
        patch_result = generate_patch_via_bridge(
            "retry-task-1",
            objective="Change x to 2 in backend/foo.py",
            plan={"steps": []},
            evidence={},
            target_files=["backend/foo.py"],
        )

    assert len(invoke_calls) == 2
    assert "RETRY" in invoke_calls[1]
    reset_mock.assert_called_once()
    assert patch_result.get("retry_used") is True
    assert patch_result.get("generation_attempts") == 2
    assert "comment-only" in (patch_result.get("retry_reason") or "")


def test_generate_patch_second_invalid_fails_safely(monkeypatch, tmp_path):
    _patch_bridge_env(monkeypatch)
    staging = tmp_path / "staging"
    staging.mkdir()

    def _mock_capture(_staging, task_id):
        diff_path = tmp_path / f"{task_id}.diff"
        diff_path.write_text(COMMENT_ONLY_DIFF, encoding="utf-8")
        return diff_path

    with patch("app.jarvis.coding_workflow.patch_bridge.provision_staging_workspace", return_value=staging), patch(
        "app.jarvis.coding_workflow.patch_bridge.invoke_cursor_cli",
        return_value={"success": True, "output": "ok"},
    ), patch("app.jarvis.coding_workflow.patch_bridge.capture_diff", side_effect=_mock_capture), patch(
        "app.jarvis.coding_workflow.patch_bridge.cleanup_staging"
    ), patch("app.jarvis.coding_workflow.patch_bridge._reset_staging_workspace"):
        with pytest.raises(PlaceholderPatchError, match="comment-only") as exc_info:
            generate_patch_via_bridge(
                "retry-task-2",
                objective="Change x",
                plan={"steps": []},
                evidence={},
            )
    err = exc_info.value
    assert err.generation_attempts == 2
    assert err.retry_used is True


def test_generate_patch_valid_first_pass_does_not_retry(monkeypatch, tmp_path):
    _patch_bridge_env(monkeypatch)
    staging = tmp_path / "staging"
    staging.mkdir()
    invoke_calls: list[str] = []

    def _mock_invoke(_staging, prompt, task_id=""):
        invoke_calls.append(prompt)
        return {"success": True, "output": "ok"}

    def _mock_capture(_staging, task_id):
        diff_path = tmp_path / f"{task_id}.diff"
        diff_path.write_text(SUBSTANTIVE_CODE_DIFF, encoding="utf-8")
        return diff_path

    with patch("app.jarvis.coding_workflow.patch_bridge.provision_staging_workspace", return_value=staging), patch(
        "app.jarvis.coding_workflow.patch_bridge.invoke_cursor_cli", side_effect=_mock_invoke
    ), patch("app.jarvis.coding_workflow.patch_bridge.capture_diff", side_effect=_mock_capture), patch(
        "app.jarvis.coding_workflow.patch_bridge.cleanup_staging"
    ), patch("app.jarvis.coding_workflow.patch_bridge._reset_staging_workspace") as reset_mock:
        patch_result = generate_patch_via_bridge(
            "retry-task-3",
            objective="Change x",
            plan={"steps": []},
            evidence={},
        )

    assert len(invoke_calls) == 1
    assert "RETRY" not in invoke_calls[0]
    reset_mock.assert_not_called()
    assert patch_result.get("retry_used") is False
    assert patch_result.get("generation_attempts") == 1


def test_acw_submit_records_retry_metadata(exec_db, monkeypatch, acw_env):
    retry_patch = {
        **MOCK_PATCH,
        "retry_used": True,
        "generation_attempts": 2,
        "retry_reason": "comment-only diff — no substantive code changes",
    }
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=retry_patch):
        detail = submit_coding_workflow(objective="Update docs safely")
    assert detail["status"] == TaskLifecycleState.WAITING_FOR_APPROVAL.value
    log_tools = [e.get("tool") for e in detail.get("execution_log", [])]
    assert "generate_patch_retry" in log_tools


def test_acw_gate2_happy_path_mock_pr(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=MOCK_TESTS_PASSED
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        approve_patch_apply(detail["task_id"])
    result = approve_pr_creation(detail["task_id"], mock_pr=True)
    assert result["status"] == TaskLifecycleState.COMPLETED.value
    status = get_phase5_status(detail["task_id"])
    assert status["workflow_type"] == WORKFLOW_TYPE
    assert status["gate1_approved"] is True
    assert status["gate2_approved"] is True


def test_acw_artifacts_endpoint(jarvis_client):
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=MOCK_PATCH):
        submit = jarvis_client.post(
            "/api/jarvis/coding-workflow/submit",
            json={"objective": "Update docs"},
        )
    task_id = submit.json()["task_id"]
    resp = jarvis_client.get(f"/api/jarvis/coding-workflow/{task_id}/artifacts")
    assert resp.status_code == 200
    assert resp.json()["task_id"] == task_id
    assert len(resp.json()["artifacts"]) >= 5


def test_acw_evidence_artifact_content(exec_db, monkeypatch, acw_env):
    detail = _submit_acw(monkeypatch)
    from app.jarvis.artifacts.storage import load_artifact_content

    for art in detail.get("artifacts", []):
        if art.get("standard_name") == "evidence.json":
            data = json.loads(load_artifact_content(art))
            assert "safety_classification" in data
            break
    else:
        pytest.fail("evidence.json artifact missing")


def _acw_http_submit(jarvis_client):
    with patch("app.jarvis.coding_workflow.service.generate_patch_via_bridge", return_value=MOCK_PATCH):
        submit = jarvis_client.post(
            "/api/jarvis/coding-workflow/submit",
            json={"objective": "Update docs for ACW HTTP regression test"},
        )
    assert submit.status_code == 200
    return submit.json()["task_id"]


def _acw_http_gate1(jarvis_client, task_id):
    with patch("app.jarvis.change_execution.service.apply_patch_in_sandbox", return_value=MOCK_APPLY_SUCCESS), patch(
        "app.jarvis.change_execution.service.run_sandbox_tests", return_value=MOCK_TESTS_PASSED
    ), patch("app.jarvis.change_execution.service.write_test_artifacts", return_value={}):
        return jarvis_client.post(
            f"/api/jarvis/coding-workflow/{task_id}/approve-apply",
            json={"actor_id": "tester"},
        )


def test_acw_http_approve_apply_returns_200_with_pending_pr(jarvis_client):
    task_id = _acw_http_submit(jarvis_client)
    resp = _acw_http_gate1(jarvis_client, task_id)
    assert resp.status_code == 200
    assert resp.json()["approval_status"] == "pending_pr"


def test_acw_http_get_detail_after_gate1(jarvis_client):
    task_id = _acw_http_submit(jarvis_client)
    gate1 = _acw_http_gate1(jarvis_client, task_id)
    assert gate1.status_code == 200

    detail = jarvis_client.get(f"/api/jarvis/coding-workflow/{task_id}")
    assert detail.status_code == 200
    body = detail.json()
    assert body["task_id"] == task_id
    assert body["approval_status"] == "pending_pr"


def _acw_http_gate2(jarvis_client, task_id):
    with patch(
        "app.jarvis.change_execution.service.approve_pr_creation",
        side_effect=lambda task_id, actor_id="dashboard", comment="", mock_pr=False: approve_pr_creation(
            task_id, actor_id=actor_id, comment=comment, mock_pr=True
        ),
    ):
        return jarvis_client.post(
            f"/api/jarvis/coding-workflow/{task_id}/approve-pr",
            json={"actor_id": "tester"},
        )


def test_acw_http_gate2_reachable_after_gate1(jarvis_client):
    task_id = _acw_http_submit(jarvis_client)
    gate1 = _acw_http_gate1(jarvis_client, task_id)
    assert gate1.status_code == 200

    gate2 = _acw_http_gate2(jarvis_client, task_id)
    assert gate2.status_code == 200
    assert gate2.json()["status"] == TaskLifecycleState.COMPLETED.value


def test_acw_http_full_flow_mock_pr(jarvis_client):
    """submit → approve-apply → GET task detail → approve-pr with mock PR."""
    task_id = _acw_http_submit(jarvis_client)

    gate1 = _acw_http_gate1(jarvis_client, task_id)
    assert gate1.status_code == 200
    assert gate1.json()["approval_status"] == "pending_pr"

    detail = jarvis_client.get(f"/api/jarvis/coding-workflow/{task_id}")
    assert detail.status_code == 200
    assert detail.json()["approval_status"] == "pending_pr"

    gate2 = _acw_http_gate2(jarvis_client, task_id)
    assert gate2.status_code == 200
    final = gate2.json()
    assert final["status"] == TaskLifecycleState.COMPLETED.value
    assert final.get("phase5", {}).get("gate1_approved") is True
    assert final.get("phase5", {}).get("gate2_approved") is True


class TestGate1FrontendSandboxValidation:
    """Gate 1 sandbox frontend build uses project-local npm scripts and deps."""

    def _write_frontend_package(self, root: Path, *, with_lock: bool = True) -> Path:
        frontend = root / "frontend"
        frontend.mkdir(parents=True)
        (frontend / "package.json").write_text(
            json.dumps({"scripts": {"build": "next build"}}, indent=2),
            encoding="utf-8",
        )
        if with_lock:
            (frontend / "package-lock.json").write_text('{"lockfileVersion": 3, "packages": {}}', encoding="utf-8")
        return frontend

    def test_frontend_build_runs_from_frontend_directory(self, tmp_path, monkeypatch):
        frontend = self._write_frontend_package(tmp_path)
        calls: list[dict[str, object]] = []

        def fake_run(cmd, **kwargs):
            calls.append({"cmd": list(cmd), "cwd": kwargs.get("cwd")})
            if cmd[:2] == ["npm", "ci"]:
                next_bin = frontend / "node_modules" / ".bin"
                next_bin.mkdir(parents=True)
                (next_bin / "next").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                (next_bin / "next").chmod(0o755)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "build ok", "")

        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner._seed_sandbox_frontend_node_modules",
            lambda **kw: {"seeded": False, "reason": "disabled for unit test"},
        )
        monkeypatch.setattr("app.jarvis.change_execution.test_runner.subprocess.run", fake_run)

        from app.jarvis.change_execution.test_runner import _run_frontend_build

        result = _run_frontend_build(cwd=tmp_path, timeout=30)

        build_calls = [c for c in calls if c["cmd"] == ["npm", "run", "build"]]
        assert build_calls, "expected npm run build to run"
        assert build_calls[0]["cwd"] == str(frontend)
        assert result["working_directory"] == str(frontend)
        assert result["passed"] is True

    def test_frontend_build_uses_npm_script_not_global_next(self, tmp_path, monkeypatch):
        frontend = self._write_frontend_package(tmp_path)
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            if cmd[:2] == ["npm", "ci"]:
                next_bin = frontend / "node_modules" / ".bin"
                next_bin.mkdir(parents=True)
                (next_bin / "next").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
                (next_bin / "next").chmod(0o755)
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner._seed_sandbox_frontend_node_modules",
            lambda **kw: {"seeded": False, "reason": "disabled for unit test"},
        )
        monkeypatch.setattr("app.jarvis.change_execution.test_runner.subprocess.run", fake_run)

        from app.jarvis.change_execution.test_runner import _run_frontend_build

        _run_frontend_build(cwd=tmp_path, timeout=30)

        assert ["npm", "run", "build"] in calls
        assert not any(cmd and cmd[0] == "next" for cmd in calls)
        assert not any(cmd[:2] == ["npx", "next"] for cmd in calls)

    def test_missing_frontend_dependencies_return_clear_gate1_error(self, tmp_path, monkeypatch):
        self._write_frontend_package(tmp_path)

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["npm", "ci"]:
                return subprocess.CompletedProcess(cmd, 1, "", "npm ERR! install failed")
            return subprocess.CompletedProcess(cmd, 127, "", "sh: next: not found")

        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner._seed_sandbox_frontend_node_modules",
            lambda **kw: {"seeded": False, "reason": "disabled for unit test"},
        )
        monkeypatch.setattr("app.jarvis.change_execution.test_runner.subprocess.run", fake_run)

        from app.jarvis.change_execution.test_runner import _run_frontend_build

        result = _run_frontend_build(cwd=tmp_path, timeout=30)

        assert result["passed"] is False
        assert "next: not found" not in (result.get("error") or "")
        assert "dependency" in (result.get("error") or "").lower()

    def test_backend_only_gate1_skips_frontend_build(self, tmp_path, monkeypatch):
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(list(cmd))
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr("app.jarvis.change_execution.test_runner.subprocess.run", fake_run)
        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner.run_tests_for_patch",
            lambda **kwargs: {"test_report": {"ok": True}, "passed": True, "summary": "Passed: 1 test(s)"},
        )
        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner.validate_clean_worktree",
            lambda workdir: {"clean": True},
        )
        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner.determine_relevant_tests",
            lambda **kwargs: ["backend/tests/test_foo.py"],
        )

        from app.jarvis.change_execution.test_runner import run_sandbox_tests

        result = run_sandbox_tests(
            task_id="gate1-backend-only",
            workdir=tmp_path,
            changed_files=["backend/app/foo.py"],
            objective="Update backend helper only",
        )

        assert result["passed"] is True
        assert result["frontend_build"]["skipped"] is True
        assert not any(cmd[:2] == ["npm", "run"] for cmd in calls)

    def test_frontend_build_seeds_workspace_node_modules(self, tmp_path, monkeypatch):
        workspace_root_path = tmp_path / "workspace"
        sandbox_root = tmp_path / "sandbox"
        workspace_frontend = workspace_root_path / "frontend"
        workspace_bin = workspace_frontend / "node_modules" / ".bin"
        workspace_bin.mkdir(parents=True)
        (workspace_bin / "next").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        (workspace_bin / "next").chmod(0o755)
        (workspace_frontend / "package.json").write_text(
            '{"scripts":{"build":"next build"}}', encoding="utf-8"
        )

        sandbox_frontend = sandbox_root / "frontend"
        sandbox_frontend.mkdir(parents=True)
        (sandbox_frontend / "package.json").write_text(
            '{"scripts":{"build":"next build"}}', encoding="utf-8"
        )

        monkeypatch.setattr(
            "app.jarvis.change_execution.test_runner._repo_frontend_dir",
            lambda: workspace_frontend,
        )

        from app.jarvis.change_execution.test_runner import _ensure_frontend_dependencies

        dep = _ensure_frontend_dependencies(frontend_dir=sandbox_frontend, timeout=30)

        assert dep.get("ok") is True
        assert dep.get("seed", {}).get("seeded") is True
        assert dep.get("seed", {}).get("method") == "hardlink_copy"
        assert (sandbox_frontend / "node_modules" / ".bin" / "next").exists()
        assert "npm ci" not in (dep.get("command") or "")
