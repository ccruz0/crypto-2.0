"""Phase 5 change execution orchestration: sandbox apply + PR creation."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.artifacts.storage import create_versioned_artifact, load_artifact_content
from app.jarvis.change_execution.audit import log_phase5_event
from app.jarvis.change_execution.config import (
    jarvis_patch_apply_enabled,
    jarvis_pr_creation_enabled,
    jarvis_require_double_approval,
    phase5_safety_status,
)
from app.jarvis.change_execution.sandbox import (
    SANDBOX_BASE,
    apply_patch_in_sandbox,
    cleanup_sandbox,
)
from app.jarvis.change_execution.test_runner import run_sandbox_tests, write_test_artifacts
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    get_execution_task,
    list_approvals,
    record_approval,
    transition_task_status,
)
from app.jarvis.execution.safety import classify_phase5_action, is_forbidden
from app.jarvis.github.pr_service import (
    build_pr_body,
    check_pr_creation_allowed,
    create_pull_request,
)
from app.jarvis.mvp.config import jarvis_enabled

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "phase5_change"
GATE_APPLY = "gate1_apply"
GATE_PR = "gate2_pr"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_patch_content(task: dict[str, Any]) -> str:
    for art in task.get("artifacts") or []:
        name = art.get("standard_name") or art.get("name") or ""
        if name == "patch.diff" or name.startswith("patch.diff"):
            try:
                return load_artifact_content(art)
            except (OSError, TypeError):
                pass
    return ""


def _get_phase5_meta(task: dict[str, Any]) -> dict[str, Any]:
    plan = task.get("plan") or {}
    return plan.get("phase5") or {}


def _set_phase5_meta(task_id: str, task: dict[str, Any], updates: dict[str, Any]) -> None:
    plan = dict(task.get("plan") or {})
    phase5 = dict(plan.get("phase5") or {})
    phase5.update(updates)
    plan["phase5"] = phase5
    plan["workflow_type"] = WORKFLOW_TYPE
    _update_task(task_id, plan_json=plan)


def get_phase5_status(task_id: str) -> dict[str, Any]:
    """Return Phase 5 safety + gate status for UI."""
    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")

    meta = _get_phase5_meta(task)
    approvals = list_approvals(task_id)
    gate1 = any(a.get("decision") == "approved_apply" for a in approvals)
    gate2 = any(a.get("decision") == "approved_pr" for a in approvals)

    flags = phase5_safety_status()
    can_apply = (
        task.get("status") == TaskLifecycleState.WAITING_FOR_APPROVAL.value
        and jarvis_patch_apply_enabled()
        and not gate1
    )
    tests_passed = meta.get("tests_passed", False)
    can_create_pr = (
        task.get("status") == TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value
        and jarvis_pr_creation_enabled()
        and flags["github_write_enabled"]
        and tests_passed
        and gate1
        and (not jarvis_require_double_approval() or not gate2)
    )

    return {
        "task_id": task_id,
        "status": task.get("status"),
        "workflow_type": WORKFLOW_TYPE,
        "safety_flags": flags,
        "gate1_approved": gate1,
        "gate2_approved": gate2,
        "can_approve_apply": can_apply,
        "can_approve_pr": can_create_pr and not gate2,
        "tests_passed": tests_passed,
        "sandbox_applied": meta.get("sandbox_applied", False),
        "pr_url": meta.get("pr_url"),
        "branch_name": meta.get("branch_name"),
        "changed_files": meta.get("changed_files", []),
        "test_results": meta.get("test_results", {}),
        "forbidden_check": meta.get("forbidden_check", {}),
    }


def approve_patch_apply(
    task_id: str,
    *,
    actor_id: str = "dashboard",
    comment: str = "",
) -> dict[str, Any]:
    """Gate 1: Approve and apply patch in isolated sandbox, then run tests."""
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")
    if not jarvis_patch_apply_enabled():
        raise RuntimeError("Patch apply disabled (JARVIS_PATCH_APPLY_ENABLED=false)")
    if is_forbidden(classify_phase5_action("patch_application")):
        raise RuntimeError("patch_application is FORBIDDEN")

    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")
    if task.get("status") != TaskLifecycleState.WAITING_FOR_APPROVAL.value:
        raise ValueError(f"task not awaiting Gate 1 approval (status={task.get('status')})")

    patch_content = _load_patch_content(task)
    if not patch_content.strip():
        raise ValueError("no patch content available")

    record_approval(task_id=task_id, decision="approved_apply", actor_id=actor_id, comment=comment)
    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_APPLY,
        action="approve_apply",
    )

    transition_task_status(task_id, TaskLifecycleState.APPLYING_PATCH, current_step="applying_patch")

    apply_result = apply_patch_in_sandbox(
        task_id=task_id,
        patch_content=patch_content,
        objective=task.get("objective", ""),
        plan=task.get("plan"),
    )

    if not apply_result.get("success"):
        error = apply_result.get("error", "sandbox apply failed")
        log_phase5_event(
            task_id=task_id,
            actor=actor_id,
            approval_gate=GATE_APPLY,
            action="apply_failed",
            branch_name=apply_result.get("branch_name", ""),
            changed_files=apply_result.get("changed_files"),
            test_result=f"failed: {error}",
        )
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error=error,
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    branch = apply_result["branch_name"]
    changed = apply_result["changed_files"]
    workdir = Path(apply_result["workdir"])

    transition_task_status(task_id, TaskLifecycleState.SANDBOX_TESTING, current_step="sandbox_testing")

    test_results = run_sandbox_tests(
        task_id=task_id,
        workdir=workdir,
        changed_files=changed,
        objective=task.get("objective", ""),
    )
    artifact_paths = write_test_artifacts(workdir, test_results)
    tests_passed = test_results.get("passed", False)

    # Store Phase 5 artifacts
    new_artifacts = []
    for name, path in artifact_paths.items():
        try:
            content = Path(path).read_text(encoding="utf-8")
            fmt = "json" if name.endswith(".json") else "markdown"
            new_artifacts.append(
                create_versioned_artifact(
                    task_id=task_id,
                    name=name,
                    content=content if fmt != "json" else json.loads(content),
                    fmt=fmt,
                    version=1,
                )
            )
        except (OSError, json.JSONDecodeError):
            pass

    if apply_result.get("applied_patch_path"):
        try:
            diff_content = Path(apply_result["applied_patch_path"]).read_text(encoding="utf-8")
            new_artifacts.append(
                create_versioned_artifact(
                    task_id=task_id,
                    name="applied_patch.diff",
                    content=diff_content,
                    fmt="text",
                    version=1,
                )
            )
        except OSError:
            pass

    existing = task.get("artifacts") or []
    _update_task(task_id, artifacts_json=[*existing, *new_artifacts])

    _set_phase5_meta(
        task_id,
        task,
        {
            "sandbox_applied": True,
            "branch_name": branch,
            "changed_files": changed,
            "tests_passed": tests_passed,
            "test_results": test_results,
            "forbidden_check": apply_result.get("forbidden_check", {}),
            "workdir": str(workdir),
        },
    )

    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_APPLY,
        action="sandbox_apply_complete",
        branch_name=branch,
        changed_files=changed,
        test_command="pytest + optional npm build",
        test_result="passed" if tests_passed else "failed",
    )

    if not tests_passed:
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error="Sandbox tests failed after patch apply",
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    transition_task_status(
        task_id,
        TaskLifecycleState.WAITING_FOR_PR_APPROVAL,
        current_step="waiting_for_pr_approval",
        approval_status="pending_pr",
    )
    return _detail(task_id)


def approve_pr_creation(
    task_id: str,
    *,
    actor_id: str = "dashboard",
    comment: str = "",
    mock_pr: bool = False,
) -> dict[str, Any]:
    """Gate 2: Approve and create GitHub PR (never merge/deploy)."""
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")

    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")
    if task.get("status") != TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value:
        raise ValueError(f"task not awaiting Gate 2 approval (status={task.get('status')})")

    meta = _get_phase5_meta(task)
    if not meta.get("tests_passed"):
        raise ValueError("tests must pass before PR creation")

    approvals = list_approvals(task_id)
    if not any(a.get("decision") == "approved_apply" for a in approvals):
        raise ValueError("Gate 1 approval required before PR creation")

    prereq = check_pr_creation_allowed(
        tests_passed=meta.get("tests_passed", False),
        patch_safety_passed=meta.get("forbidden_check", {}).get("passed", True),
        gate2_approved=False,
    )
    if not mock_pr and not prereq["allowed"]:
        raise RuntimeError("; ".join(prereq["reasons"]))

    record_approval(task_id=task_id, decision="approved_pr", actor_id=actor_id, comment=comment)
    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_PR,
        action="approve_pr",
    )

    transition_task_status(task_id, TaskLifecycleState.CREATING_PR, current_step="creating_pr")

    branch = meta.get("branch_name", f"jarvis/task-{task_id[:12]}")
    changed = meta.get("changed_files", [])
    workdir = Path(meta.get("workdir") or str(SANDBOX_BASE / task_id))
    review = task.get("review") or {}
    test_results = meta.get("test_results") or {}

    safety_report = {
        "passed": meta.get("forbidden_check", {}).get("passed", True),
        "blocked_paths": meta.get("forbidden_check", {}).get("blocked_paths", []),
        "flags": phase5_safety_status(),
    }

    body = build_pr_body(
        task_id=task_id,
        objective=task.get("objective", ""),
        changed_files=changed,
        test_results=test_results,
        review=review,
        safety_report=safety_report,
        artifact_links=[a.get("name", "") for a in task.get("artifacts") or []],
    )

    title = f"[Jarvis] {task.get('objective', '')[:80]}"
    pr_result = create_pull_request(
        task_id=task_id,
        branch_name=branch,
        title=title,
        body=body,
        workdir=workdir,
        mock=mock_pr or not jarvis_pr_creation_enabled(),
    )

    if not pr_result.get("success"):
        error = pr_result.get("error", "PR creation failed")
        log_phase5_event(
            task_id=task_id,
            actor=actor_id,
            approval_gate=GATE_PR,
            action="pr_creation_failed",
            branch_name=branch,
            test_result=error,
        )
        transition_task_status(task_id, TaskLifecycleState.FAILED, error=error, completed_at=_now_iso())
        return _detail(task_id)

    pr_url = pr_result.get("pr_url", "")
    _set_phase5_meta(task_id, task, {"pr_url": pr_url, "pr_created": True, "pr_mock": pr_result.get("mock", False)})

    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_PR,
        action="pr_created",
        branch_name=branch,
        changed_files=changed,
        pr_url=pr_url,
    )

    transition_task_status(task_id, TaskLifecycleState.PR_CREATED, current_step="pr_created")
    transition_task_status(
        task_id,
        TaskLifecycleState.COMPLETED,
        final_answer=f"PR created: {pr_url}. Merge and deploy disabled.",
        completed_at=_now_iso(),
        approval_status="approved",
    )
    return _detail(task_id)


def reject_change_execution(
    task_id: str,
    *,
    actor_id: str = "dashboard",
    comment: str = "",
) -> dict[str, Any]:
    """Reject at any Phase 5 gate."""
    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")

    allowed_statuses = {
        TaskLifecycleState.WAITING_FOR_APPROVAL.value,
        TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value,
        TaskLifecycleState.APPLYING_PATCH.value,
        TaskLifecycleState.SANDBOX_TESTING.value,
    }
    if task.get("status") not in allowed_statuses:
        raise ValueError(f"task cannot be rejected (status={task.get('status')})")

    record_approval(task_id=task_id, decision="rejected", actor_id=actor_id, comment=comment)
    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate="reject",
        action="reject",
    )
    cleanup_sandbox(task_id)
    transition_task_status(
        task_id,
        TaskLifecycleState.CANCELLED,
        approval_status="rejected",
        final_answer="Change rejected by approver.",
        completed_at=_now_iso(),
    )
    return _detail(task_id)


def _detail(task_id: str) -> dict[str, Any]:
    from app.jarvis.execution.audit import list_execution_log

    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    row["execution_log"] = list_execution_log(task_id)
    row["approvals"] = list_approvals(task_id)
    row["workflow_type"] = WORKFLOW_TYPE
    row["phase5"] = get_phase5_status(task_id)
    return row
