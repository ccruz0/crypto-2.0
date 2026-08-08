"""Jarvis Phase B: Send to LAB trial (isolated sandbox apply + tests).

Honest scope for B1:
- Uses the existing isolated sandbox under {tempdir}/jarvis-sandbox/{task_id}
  (same apply/test machinery as Phase-5 Gate 1).
- Does NOT require JARVIS_PATCH_APPLY_ENABLED — LAB trial is intentionally separate
  from the prod Gate-1 flag so prod safety flags can stay off.
- Does NOT orchestrate a remote atp-lab-builder host (that's B2).
- Never creates PRs or writes to production.
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.jarvis.artifacts.storage import create_versioned_artifact, load_artifact_content
from app.jarvis.change_execution.audit import log_phase5_event
from app.jarvis.change_execution.config import jarvis_lab_trial_enabled, phase5_safety_status
from app.jarvis.change_execution.patch_quality import is_stub_patch, stub_refusal_message
from app.jarvis.change_execution.sandbox import apply_patch_in_sandbox
from app.jarvis.change_execution.test_runner import run_sandbox_tests, write_test_artifacts
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    get_execution_task,
    list_approvals,
    record_approval,
    transition_task_status,
)
from app.jarvis.mvp.config import jarvis_enabled

logger = logging.getLogger(__name__)

LAB_MECHANISM = "isolated_sandbox"
LAB_MECHANISM_LABEL = (
    "LAB trial via isolated sandbox (apply + tests on a temp copy of the repo). "
    "Remote LAB host orchestration is not wired yet (Phase B2)."
)
GATE_LAB = "lab_trial"

_LAB_LOCKS_GUARD = threading.Lock()
_LAB_LOCKS: dict[str, threading.Lock] = {}


def _task_lab_lock(task_id: str) -> threading.Lock:
    with _LAB_LOCKS_GUARD:
        lock = _LAB_LOCKS.get(task_id)
        if lock is None:
            lock = threading.Lock()
            _LAB_LOCKS[task_id] = lock
        return lock


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_patch_content(task: dict[str, Any]) -> str:
    """Load the newest patch.diff artifact (highest version, else last match)."""
    matches: list[dict[str, Any]] = []
    for art in task.get("artifacts") or []:
        name = art.get("standard_name") or art.get("name") or ""
        if name == "patch.diff" or str(name).startswith("patch.diff"):
            matches.append(art)
    if not matches:
        return ""

    def _version_key(art: dict[str, Any]) -> int:
        try:
            return int(art.get("version") or 0)
        except (TypeError, ValueError):
            return 0

    matches.sort(key=_version_key)
    # Prefer highest version; ties keep later list order via stable sort.
    for art in reversed(matches):
        try:
            return load_artifact_content(art)
        except (OSError, TypeError):
            continue
    return ""


def _get_lab_meta(task: dict[str, Any]) -> dict[str, Any]:
    plan = task.get("plan") or {}
    return dict(plan.get("lab_trial") or {})


def _set_lab_meta(task_id: str, task: dict[str, Any] | None, updates: dict[str, Any]) -> None:
    """Merge lab_trial updates onto the latest persisted plan (avoids stale overwrites)."""
    fresh = get_execution_task(task_id) or task or {}
    plan = dict(fresh.get("plan") or {})
    lab = dict(plan.get("lab_trial") or {})
    lab.update(updates)
    plan["lab_trial"] = lab
    _update_task(task_id, plan_json=plan)


def _plain_summary(*, status: str, tests_passed: bool | None, error: str | None) -> str:
    if status == "testing":
        return "Testing in LAB — applying the patch in isolation and running tests."
    if status == "passed":
        return "LAB passed — isolated apply and tests succeeded. Promote to production comes in Phase C."
    if status == "failed":
        why = error or "apply or tests failed"
        return f"LAB failed — {why}"
    if status == "refused":
        return error or stub_refusal_message()
    if status == "not_started":
        return "Not sent to LAB yet."
    return status


def assess_lab_eligibility(task: dict[str, Any]) -> dict[str, Any]:
    """Return whether Send to LAB can run, with a plain-language reason if not."""
    if not jarvis_lab_trial_enabled():
        return {
            "can_send_to_lab": False,
            "reason": "Send to LAB is disabled (JARVIS_LAB_TRIAL_ENABLED=false).",
        }
    if not jarvis_enabled():
        return {"can_send_to_lab": False, "reason": "Jarvis is disabled (JARVIS_ENABLED=false)."}

    status = task.get("status")
    lab = _get_lab_meta(task)
    if lab.get("status") == "testing":
        return {"can_send_to_lab": False, "reason": "LAB trial already in progress."}
    if lab.get("status") == "passed":
        return {
            "can_send_to_lab": False,
            "reason": "LAB already passed for this trial. Promote to production arrives in Phase C.",
        }
    if status != TaskLifecycleState.WAITING_FOR_APPROVAL.value:
        return {
            "can_send_to_lab": False,
            "reason": f"Task is not ready for LAB (status={status}).",
        }

    patch = _load_patch_content(task)
    if not patch.strip():
        return {
            "can_send_to_lab": False,
            "reason": "No patch.diff artifact on this task — nothing to try in LAB.",
        }
    if is_stub_patch(patch):
        return {"can_send_to_lab": False, "reason": stub_refusal_message()}

    return {"can_send_to_lab": True, "reason": ""}


def get_lab_trial_status(task_id: str) -> dict[str, Any]:
    """Plain-language LAB trial status for Ops → Jarvis."""
    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")

    lab = _get_lab_meta(task)
    eligibility = assess_lab_eligibility(task)
    status = lab.get("status") or "not_started"
    tests_passed = lab.get("tests_passed")
    error = lab.get("error")
    summary = lab.get("summary") or _plain_summary(
        status=status, tests_passed=tests_passed, error=error
    )

    return {
        "task_id": task_id,
        "status": status,
        "summary": summary,
        "mechanism": lab.get("mechanism") or LAB_MECHANISM,
        "mechanism_label": lab.get("mechanism_label") or LAB_MECHANISM_LABEL,
        "can_send_to_lab": eligibility["can_send_to_lab"],
        "ineligible_reason": eligibility["reason"],
        "tests_passed": bool(tests_passed) if tests_passed is not None else False,
        "sandbox_applied": bool(lab.get("sandbox_applied")),
        "changed_files": lab.get("changed_files") or [],
        "branch_name": lab.get("branch_name"),
        "test_results": lab.get("test_results") or {},
        "error": error,
        "can_promote": bool(lab.get("status") == "passed" and lab.get("tests_passed")),
        "promote_available": False,  # Phase C
        "promote_hint": (
            "Promote to production unlocks in Phase C after LAB green (opens a PR; you still merge/deploy)."
            if lab.get("status") == "passed"
            else "Send to LAB and get a green result before Promote becomes available."
        ),
        "safety_flags": phase5_safety_status(),
    }


def send_to_lab(
    task_id: str,
    *,
    actor_id: str = "dashboard",
    comment: str = "",
) -> dict[str, Any]:
    """
    Operator action: package patch → apply in isolated sandbox → run tests.

    Does not flip or require JARVIS_PATCH_APPLY_ENABLED / PR / github_write.
    """
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")
    if not jarvis_lab_trial_enabled():
        raise RuntimeError("Send to LAB disabled (JARVIS_LAB_TRIAL_ENABLED=false)")

    lock = _task_lab_lock(task_id)
    if not lock.acquire(blocking=False):
        raise ValueError("LAB trial already in progress.")
    try:
        return _send_to_lab_locked(task_id, actor_id=actor_id, comment=comment)
    finally:
        lock.release()


def _lab_fail_and_retryable(
    task_id: str,
    task: dict[str, Any],
    *,
    actor_id: str,
    action: str,
    error: str,
    apply_result: dict[str, Any] | None = None,
    test_results: dict[str, Any] | None = None,
    branch: str | None = None,
    changed: list[str] | None = None,
    workdir: Path | None = None,
) -> dict[str, Any]:
    """Record LAB failure and return task to waiting_for_approval for retry."""
    summary = _plain_summary(status="failed", tests_passed=False, error=error)
    meta: dict[str, Any] = {
        "status": "failed",
        "sandbox_applied": bool(apply_result and apply_result.get("success")),
        "tests_passed": False,
        "error": error,
        "summary": summary,
        "completed_at": _now_iso(),
    }
    if branch is not None:
        meta["branch_name"] = branch
    if changed is not None:
        meta["changed_files"] = changed
    if test_results is not None:
        meta["test_results"] = test_results
    if apply_result is not None:
        meta["forbidden_check"] = apply_result.get("forbidden_check", {})
    if workdir is not None:
        meta["workdir"] = str(workdir)
    _set_lab_meta(task_id, task, meta)
    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_LAB,
        action=action,
        branch_name=branch or (apply_result or {}).get("branch_name", ""),
        changed_files=changed if changed is not None else (apply_result or {}).get("changed_files"),
        test_result=f"failed: {error}",
    )
    transition_task_status(
        task_id,
        TaskLifecycleState.WAITING_FOR_APPROVAL,
        current_step="lab_failed_retryable",
        error=summary,
        approval_status="pending",
    )
    return _detail(task_id)


def _send_to_lab_locked(
    task_id: str,
    *,
    actor_id: str,
    comment: str,
) -> dict[str, Any]:
    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")

    eligibility = assess_lab_eligibility(task)
    if not eligibility["can_send_to_lab"]:
        # Persist refused state when it's a stub/empty patch for UI visibility.
        reason = eligibility["reason"]
        if "stub" in reason.lower() or "no patch" in reason.lower() or "No real patch" in reason:
            _set_lab_meta(
                task_id,
                task,
                {
                    "status": "refused",
                    "error": reason,
                    "summary": reason,
                    "mechanism": LAB_MECHANISM,
                    "mechanism_label": LAB_MECHANISM_LABEL,
                    "updated_at": _now_iso(),
                },
            )
            raise ValueError(reason)
        raise ValueError(reason)

    patch_content = _load_patch_content(task)

    record_approval(
        task_id=task_id,
        decision="sent_to_lab",
        actor_id=actor_id,
        comment=comment or "Send to LAB (isolated sandbox trial)",
    )
    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_LAB,
        action="send_to_lab",
    )

    started_at = _now_iso()
    _set_lab_meta(
        task_id,
        task,
        {
            "status": "testing",
            "summary": _plain_summary(status="testing", tests_passed=None, error=None),
            "mechanism": LAB_MECHANISM,
            "mechanism_label": LAB_MECHANISM_LABEL,
            "started_at": started_at,
            "error": None,
        },
    )

    transition_task_status(task_id, TaskLifecycleState.APPLYING_PATCH, current_step="lab_applying_patch")

    apply_result = apply_patch_in_sandbox(
        task_id=task_id,
        patch_content=patch_content,
        objective=task.get("objective", ""),
        plan=task.get("plan"),
    )

    if not apply_result.get("success"):
        error = apply_result.get("error", "LAB sandbox apply failed")
        return _lab_fail_and_retryable(
            task_id,
            task,
            actor_id=actor_id,
            action="lab_apply_failed",
            error=error,
            apply_result=apply_result,
        )

    branch = apply_result["branch_name"]
    changed = apply_result["changed_files"]
    workdir = Path(apply_result["workdir"])

    transition_task_status(task_id, TaskLifecycleState.SANDBOX_TESTING, current_step="lab_testing")

    test_results = run_sandbox_tests(
        task_id=task_id,
        workdir=workdir,
        changed_files=changed,
        objective=task.get("objective", ""),
    )
    artifact_paths = write_test_artifacts(workdir, test_results)
    tests_passed = bool(test_results.get("passed", False))

    new_artifacts = []
    for name, path in artifact_paths.items():
        try:
            content = Path(path).read_text(encoding="utf-8")
            fmt = "json" if name.endswith(".json") else "markdown"
            new_artifacts.append(
                create_versioned_artifact(
                    task_id=task_id,
                    name=f"lab_{name}",
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
                    name="lab_applied_patch.diff",
                    content=diff_content,
                    fmt="text",
                    version=1,
                )
            )
        except OSError:
            pass

    fresh = get_execution_task(task_id) or task
    existing = fresh.get("artifacts") or []
    _update_task(task_id, artifacts_json=[*existing, *new_artifacts])

    if not tests_passed:
        error = "LAB tests failed after isolated patch apply"
        return _lab_fail_and_retryable(
            task_id,
            fresh,
            actor_id=actor_id,
            action="lab_tests_failed",
            error=error,
            apply_result=apply_result,
            test_results=test_results,
            branch=branch,
            changed=changed,
            workdir=workdir,
        )

    summary = _plain_summary(status="passed", tests_passed=True, error=None)
    _set_lab_meta(
        task_id,
        fresh,
        {
            "status": "passed",
            "sandbox_applied": True,
            "branch_name": branch,
            "changed_files": changed,
            "tests_passed": True,
            "test_results": test_results,
            "forbidden_check": apply_result.get("forbidden_check", {}),
            "workdir": str(workdir),
            "error": None,
            "summary": summary,
            "completed_at": _now_iso(),
        },
    )

    # Also stash phase5 meta for Advanced views (tests green) without Gate-1 approval.
    plan = dict((get_execution_task(task_id) or {}).get("plan") or {})
    phase5 = dict(plan.get("phase5") or {})
    phase5.update(
        {
            "sandbox_applied": True,
            "branch_name": branch,
            "changed_files": changed,
            "tests_passed": True,
            "test_results": test_results,
            "forbidden_check": apply_result.get("forbidden_check", {}),
            "workdir": str(workdir),
            "via_lab_trial": True,
        }
    )
    plan["phase5"] = phase5
    _update_task(task_id, plan_json=plan)

    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_LAB,
        action="lab_trial_passed",
        branch_name=branch,
        changed_files=changed,
        test_command="pytest + optional npm build",
        test_result="passed",
    )

    # Park in waiting_for_pr_approval as "LAB green / ready to promote later".
    # Gate 2 / Promote remain blocked until Phase C (no approved_apply / flags).
    transition_task_status(
        task_id,
        TaskLifecycleState.WAITING_FOR_PR_APPROVAL,
        current_step="lab_passed_awaiting_promote",
        approval_status="pending",
        final_answer=summary,
    )
    try:
        from app.services.approval_queue_monitor import dedupe_jarvis_waiting_for_task

        dedupe_jarvis_waiting_for_task(task_id)
    except Exception:
        pass
    return _detail(task_id)


def _detail(task_id: str) -> dict[str, Any]:
    from app.jarvis.execution.audit import list_execution_log

    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    row["execution_log"] = list_execution_log(task_id)
    row["approvals"] = list_approvals(task_id)
    plan = row.get("plan") or {}
    row["workflow_type"] = plan.get("workflow_type") or "phase4_change"
    row["lab_trial"] = get_lab_trial_status(task_id)
    return row
