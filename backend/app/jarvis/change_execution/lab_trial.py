"""Jarvis Phase B/C: Send to LAB trial + Promote to production (open PR).

Honest scope:
- B1: Uses the existing isolated sandbox under {tempdir}/jarvis-sandbox/{task_id}
  (same apply/test machinery as Phase-5 Gate 1).
- Does NOT require JARVIS_PATCH_APPLY_ENABLED — LAB trial is intentionally separate
  from the prod Gate-1 flag so prod safety flags can stay off.
- Does NOT orchestrate a remote atp-lab-builder host (that's B2).
- Phase C Promote opens a GitHub PR only when LAB is green and the operator clicks.
  Gated by JARVIS_PROMOTE_PR_ENABLED (default false). Never merges or deploys.
  Does NOT require broad JARVIS_PR_CREATION_ENABLED / JARVIS_GITHUB_WRITE_ENABLED.
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
from app.jarvis.change_execution.config import (
    jarvis_lab_trial_enabled,
    jarvis_promote_pr_enabled,
    phase5_safety_status,
)
from app.jarvis.change_execution.patch_quality import is_stub_patch, stub_refusal_message
from app.jarvis.change_execution.sandbox import SANDBOX_BASE, apply_patch_in_sandbox
from app.jarvis.change_execution.test_runner import run_sandbox_tests, write_test_artifacts
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    get_execution_task,
    list_approvals,
    record_approval,
    transition_task_status,
)
from app.jarvis.github.pr_service import (
    build_pr_body,
    check_lab_promote_pr_allowed,
    create_pull_request,
    prepare_sandbox_branch_for_push,
)
from app.jarvis.mvp.config import jarvis_enabled

logger = logging.getLogger(__name__)

LAB_MECHANISM = "isolated_sandbox"
LAB_MECHANISM_LABEL = (
    "LAB trial via isolated sandbox (apply + tests on a temp copy of the repo). "
    "Remote LAB host orchestration is not wired yet (Phase B2)."
)
GATE_LAB = "lab_trial"
GATE_PROMOTE = "lab_promote"

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
        return (
            "LAB passed — isolated apply and tests succeeded. "
            "You can Promote to production to open a PR (you still merge and deploy)."
        )
    if status == "promoted":
        return "Promoted — PR opened. Merge and deploy yourself when ready."
    if status == "failed":
        why = error or "apply or tests failed"
        return f"LAB failed — {why}"
    if status == "refused":
        return error or stub_refusal_message()
    if status == "not_started":
        return "Not sent to LAB yet."
    return status


def _promote_hint(lab: dict[str, Any], *, can_promote: bool, promote_available: bool) -> str:
    if lab.get("pr_url") or lab.get("status") == "promoted":
        url = lab.get("pr_url") or ""
        return (
            f"PR already opened{': ' + url if url else ''}. "
            "Merge and deploy yourself — Jarvis will not."
        )
    if lab.get("status") != "passed" or not lab.get("tests_passed"):
        return "Send to LAB and get a green result before Promote becomes available."
    if not jarvis_promote_pr_enabled():
        return (
            "LAB is green. Enable Promote on the host: set JARVIS_PROMOTE_PR_ENABLED=true "
            "in secrets/runtime.env and restart the backend. Promote opens a PR only; "
            "you still merge and deploy. Keep Gate-2 flags (PR_CREATION / GITHUB_WRITE) off."
        )
    if promote_available or can_promote:
        return "LAB is green. Promote opens a GitHub PR — you still merge and deploy."
    return "Promote is not available for this trial."


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
            "reason": "LAB already passed for this trial. Use Promote to production when ready.",
        }
    if lab.get("status") == "promoted" or lab.get("pr_created"):
        return {
            "can_send_to_lab": False,
            "reason": "Already promoted (PR opened). Merge/deploy yourself.",
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

    patch = _load_patch_content(task)
    stub = is_stub_patch(patch) if patch.strip() else False
    already = bool(lab.get("pr_created") or lab.get("pr_url") or status == "promoted")
    lab_passed = status == "passed" and bool(tests_passed)
    can_promote = lab_passed and not already and not stub
    prereq = check_lab_promote_pr_allowed(
        lab_passed=lab_passed or status == "promoted",
        tests_passed=bool(tests_passed),
        patch_safety_passed=bool(lab.get("forbidden_check", {}).get("passed", True)),
        stub_patch=stub,
        already_promoted=already,
    )
    # Button unlock: LAB green + dedicated flag + not stub + not already promoted.
    promote_available = bool(can_promote and jarvis_promote_pr_enabled() and prereq["allowed"])

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
        "can_promote": can_promote,
        "promote_available": promote_available,
        "promote_hint": _promote_hint(
            lab, can_promote=can_promote, promote_available=promote_available
        ),
        "pr_url": lab.get("pr_url"),
        "pr_created": bool(lab.get("pr_created")),
        "promote_block_reasons": prereq["reasons"] if not promote_available else [],
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


def promote_to_production(
    task_id: str,
    *,
    actor_id: str = "dashboard",
    comment: str = "",
    mock_pr: bool = False,
) -> dict[str, Any]:
    """
    Operator action after LAB green: open a GitHub PR (never merge/deploy).

    Human gates: Send to LAB (earlier) + Promote click (this). Uses
    JARVIS_PROMOTE_PR_ENABLED only — does not enable broad Gate-2 write flags.
    Stub patches are refused.
    """
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")
    if not jarvis_promote_pr_enabled() and not mock_pr:
        raise RuntimeError(
            "Promote disabled (JARVIS_PROMOTE_PR_ENABLED=false). "
            "Enable on the host to allow opening a PR after LAB green."
        )

    lock = _task_lab_lock(task_id)
    if not lock.acquire(blocking=False):
        raise ValueError("LAB trial or promote already in progress.")
    try:
        return _promote_locked(task_id, actor_id=actor_id, comment=comment, mock_pr=mock_pr)
    finally:
        lock.release()


def _promote_locked(
    task_id: str,
    *,
    actor_id: str,
    comment: str,
    mock_pr: bool,
) -> dict[str, Any]:
    task = get_execution_task(task_id)
    if task is None:
        raise LookupError("task not found")

    lab = _get_lab_meta(task)
    if task.get("status") != TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value:
        raise ValueError(
            f"Task is not ready to promote (status={task.get('status')}). "
            "LAB must pass first."
        )
    if lab.get("status") != "passed" or not lab.get("tests_passed"):
        raise ValueError("LAB must pass before Promote to production.")

    patch = _load_patch_content(task)
    stub = is_stub_patch(patch)
    already = bool(lab.get("pr_created") or lab.get("pr_url"))
    prereq = check_lab_promote_pr_allowed(
        lab_passed=True,
        tests_passed=True,
        patch_safety_passed=bool(lab.get("forbidden_check", {}).get("passed", True)),
        stub_patch=stub,
        already_promoted=already,
    )
    if stub:
        raise ValueError(stub_refusal_message() + " Stub patches cannot be promoted.")
    if already:
        raise ValueError("Already promoted for this trial.")
    if not mock_pr and not prereq["allowed"]:
        raise RuntimeError("; ".join(prereq["reasons"]))

    # Double-approval spirit: require prior Send to LAB approval decision.
    approvals = list_approvals(task_id)
    if not any(a.get("decision") == "sent_to_lab" for a in approvals):
        raise ValueError("Send to LAB approval missing — cannot promote.")

    record_approval(
        task_id=task_id,
        decision="promoted_pr",
        actor_id=actor_id,
        comment=comment or "Promote to production (open PR after LAB green)",
    )
    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_PROMOTE,
        action="promote_to_production",
    )

    transition_task_status(task_id, TaskLifecycleState.CREATING_PR, current_step="lab_promoting_pr")

    branch = lab.get("branch_name") or f"jarvis/task-{task_id[:12]}"
    changed = lab.get("changed_files") or []
    workdir = Path(lab.get("workdir") or str(SANDBOX_BASE / task_id))
    review = task.get("review") or {}
    test_results = lab.get("test_results") or {}

    safety_report = {
        "passed": lab.get("forbidden_check", {}).get("passed", True),
        "blocked_paths": lab.get("forbidden_check", {}).get("blocked_paths", []),
        "flags": phase5_safety_status(),
        "via": "lab_promote",
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
    body = (
        "## Jarvis Promote to production (after LAB green)\n\n"
        "LAB apply + tests passed. This PR was opened by **Promote to production**. "
        "**Merge and deploy are still human steps — Jarvis will not merge or deploy.**\n\n"
        + body
    )

    if not mock_pr:
        prep = prepare_sandbox_branch_for_push(
            workdir=workdir,
            branch_name=branch,
            commit_message=f"[Jarvis LAB promote] {task.get('objective', '')[:72]}",
            changed_files=list(changed),
        )
        if not prep.get("ok"):
            error = prep.get("error", "sandbox prepare for push failed")
            log_phase5_event(
                task_id=task_id,
                actor=actor_id,
                approval_gate=GATE_PROMOTE,
                action="promote_prepare_failed",
                branch_name=branch,
                test_result=error,
            )
            # Stay promote-ready so Carlos can retry after fixing remote/gh.
            transition_task_status(
                task_id,
                TaskLifecycleState.WAITING_FOR_PR_APPROVAL,
                current_step="lab_passed_awaiting_promote",
                error=error,
                approval_status="pending",
            )
            _set_lab_meta(
                task_id,
                task,
                {"promote_error": error, "updated_at": _now_iso()},
            )
            raise RuntimeError(error)

    title = f"[Jarvis LAB] {task.get('objective', '')[:80]}"
    pr_result = create_pull_request(
        task_id=task_id,
        branch_name=branch,
        title=title,
        body=body,
        workdir=workdir,
        mock=mock_pr,
        via_lab_promote=True,
    )

    if not pr_result.get("success"):
        error = pr_result.get("error", "PR creation failed")
        log_phase5_event(
            task_id=task_id,
            actor=actor_id,
            approval_gate=GATE_PROMOTE,
            action="promote_pr_failed",
            branch_name=branch,
            test_result=error,
        )
        transition_task_status(
            task_id,
            TaskLifecycleState.WAITING_FOR_PR_APPROVAL,
            current_step="lab_passed_awaiting_promote",
            error=error,
            approval_status="pending",
        )
        _set_lab_meta(task_id, task, {"promote_error": error, "updated_at": _now_iso()})
        raise RuntimeError(error)

    pr_url = pr_result.get("pr_url", "")
    summary = _plain_summary(status="promoted", tests_passed=True, error=None)
    if pr_url:
        summary = f"{summary} PR: {pr_url}"
    _set_lab_meta(
        task_id,
        task,
        {
            "status": "promoted",
            "pr_url": pr_url,
            "pr_created": True,
            "pr_mock": bool(pr_result.get("mock")),
            "summary": summary,
            "promote_error": None,
            "promoted_at": _now_iso(),
            "promoted_by": actor_id,
        },
    )

    # Mirror into phase5 meta for Advanced views.
    fresh = get_execution_task(task_id) or task
    plan = dict(fresh.get("plan") or {})
    phase5 = dict(plan.get("phase5") or {})
    phase5.update(
        {
            "pr_url": pr_url,
            "pr_created": True,
            "pr_mock": bool(pr_result.get("mock")),
            "via_lab_promote": True,
        }
    )
    plan["phase5"] = phase5
    _update_task(task_id, plan_json=plan)

    log_phase5_event(
        task_id=task_id,
        actor=actor_id,
        approval_gate=GATE_PROMOTE,
        action="promote_pr_created",
        branch_name=branch,
        changed_files=changed,
        pr_url=pr_url,
    )

    final = (
        f"PR opened: {pr_url}. Merge and deploy yourself — Jarvis will not."
        if pr_url
        else "PR opened. Merge and deploy yourself — Jarvis will not."
    )
    if pr_result.get("mock"):
        final = f"[Mock] {final}"

    transition_task_status(task_id, TaskLifecycleState.PR_CREATED, current_step="lab_promoted_pr_created")
    transition_task_status(
        task_id,
        TaskLifecycleState.COMPLETED,
        final_answer=final,
        completed_at=_now_iso(),
        approval_status="approved",
        current_step="lab_promoted_awaiting_human_merge",
    )
    return _detail(task_id)


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

    # Park in waiting_for_pr_approval as "LAB green / ready to promote".
    # Promote remains blocked until operator clicks + JARVIS_PROMOTE_PR_ENABLED.
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
