"""Jarvis Phase 4 change workflow orchestration (no patch application)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.jarvis.agents.patch_agent import create_patch, update_patch
from app.jarvis.agents.planner_agent import build_plan, plan_to_dict
from app.jarvis.agents.repository_agent import investigate_objective
from app.jarvis.agents.reviewer_agent import review_patch
from app.jarvis.agents.test_agent import run_tests_for_patch
from app.jarvis.artifacts.storage import create_versioned_artifact
from app.jarvis.execution.audit import list_execution_log, log_execution_event
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    create_execution_task,
    get_execution_task,
    list_approvals,
    list_execution_tasks,
    record_approval,
    transition_task_status,
)
from app.jarvis.execution.safety import SafetyLevel, classify_change_objective, is_forbidden
from app.jarvis.execution.result_validation import (
    apply_validation_to_review,
    validate_task_result,
)
from app.jarvis.github.integration import github_readonly_summary
from app.jarvis.mvp.config import jarvis_dry_run_only, jarvis_enabled
from app.jarvis.repository.graph import build_repository_graph
from app.jarvis.repository.persistence import refresh_repository_metadata

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "phase4_change"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit(task_id: str, agent: str, tool: str, inp: str, out: str, ms: int = 0) -> None:
    log_execution_event(
        task_id=task_id,
        agent=agent,
        tool=tool,
        input_summary=inp[:500],
        output_summary=out[:500],
        duration_ms=ms,
    )


def _store_phase4_artifacts(
    task_id: str,
    *,
    patch: dict[str, Any],
    review: dict[str, Any],
    tests: dict[str, Any],
    repo_report: dict[str, Any],
    version: int = 1,
) -> list[dict[str, Any]]:
    artifacts = [
        create_versioned_artifact(
            task_id=task_id,
            name="patch.diff",
            content=patch.get("unified_diff", ""),
            fmt="text",
            version=version,
            metadata={"patch_id": patch.get("patch_id"), "risk_score": patch.get("risk_assessment", {}).get("risk_score")},
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="review.md",
            content=review.get("review_report", ""),
            fmt="markdown",
            version=version,
            metadata={"risk_score": review.get("risk_score"), "recommendation": review.get("approval_recommendation")},
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="tests.json",
            content=tests,
            fmt="json",
            version=version,
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="repository_report.json",
            content=repo_report,
            fmt="json",
            version=version,
        ),
    ]
    return artifacts


def submit_change_task(
    *,
    objective: str,
    priority: str = "normal",
    target_files: list[str] | None = None,
    dry_run: bool = True,
    run_tests: bool = True,
) -> dict[str, Any]:
    """Run Phase 4 change workflow: plan → investigate → patch → review → test → approval."""
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")
    if jarvis_dry_run_only() and not dry_run:
        raise RuntimeError("Non-dry-run blocked while JARVIS_DRY_RUN_ONLY=true")

    objective_text = (objective or "").strip()
    if is_forbidden(classify_change_objective(objective_text)):
        task_id = str(uuid.uuid4())
        create_execution_task(task_id=task_id, objective=objective_text, priority=priority, dry_run=dry_run)
        _audit(task_id, "service", "submit_change", objective_text, "FORBIDDEN objective")
        transition_task_status(task_id, TaskLifecycleState.PLANNING, started_at=_now_iso())
        transition_task_status(task_id, TaskLifecycleState.FAILED, error="Objective classified as FORBIDDEN", completed_at=_now_iso())
        return _detail(task_id)

    task_id = str(uuid.uuid4())
    create_execution_task(task_id=task_id, objective=objective_text, priority=priority, dry_run=dry_run)
    _audit(task_id, "service", "submit_change", objective_text, "queued")
    _update_task(task_id, current_step="planning", plan_json={"workflow_type": WORKFLOW_TYPE})

    # Planning
    transition_task_status(task_id, TaskLifecycleState.PLANNING, started_at=_now_iso())
    plan = build_plan(objective_text)
    plan_dict = plan_to_dict(plan)
    plan_dict["workflow_type"] = WORKFLOW_TYPE
    _update_task(task_id, plan_json=plan_dict, estimated_cost_usd=plan.total_estimated_cost_usd)
    _audit(task_id, "planner_agent", "build_plan", objective_text, f"steps={len(plan.steps)}")

    # Investigating
    transition_task_status(task_id, TaskLifecycleState.INVESTIGATING, current_step="investigating")
    repo_meta = refresh_repository_metadata(incremental=True)
    repo_report = repo_meta.get("report", {})
    graph = build_repository_graph(repo_report)
    investigation = investigate_objective(objective_text)
    investigation["graph"] = graph.to_dict()
    investigation["github"] = github_readonly_summary()
    if target_files:
        investigation["target_files"] = target_files
    investigation["modules"] = repo_report.get("modules", [])
    investigation["findings"] = investigation.get("findings", {})
    _audit(task_id, "repository_agent", "investigate", objective_text, f"modules={len(repo_report.get('modules', []))}")

    # Patch generation (SAFE — no application)
    transition_task_status(task_id, TaskLifecycleState.PATCH_READY, current_step="patch_generation")
    patch = create_patch(objective=objective_text, repository_analysis=investigation, target_files=target_files)
    _audit(task_id, "patch_agent", "create_patch", objective_text, patch.get("patch_summary", "")[:200])

    # Review
    transition_task_status(task_id, TaskLifecycleState.REVIEWING, current_step="reviewing")
    review = review_patch(patch=patch, repository_analysis=investigation)
    _audit(task_id, "reviewer_agent", "review_patch", patch.get("patch_id", ""), f"risk={review.get('risk_score')}")

    # Testing
    transition_task_status(task_id, TaskLifecycleState.TESTING, current_step="testing")
    test_result = run_tests_for_patch(patch=patch, objective=objective_text, dry_run=not run_tests or dry_run)
    if test_result.get("test_report"):
        review = review_patch(patch=patch, repository_analysis=investigation, test_results=test_result["test_report"])
    _audit(task_id, "test_agent", "run_tests", objective_text, test_result.get("summary", ""))

    # Store versioned artifacts
    artifacts = _store_phase4_artifacts(
        task_id,
        patch=patch,
        review=review,
        tests=test_result,
        repo_report={"report": repo_report, "investigation": investigation},
    )

    validation = validate_task_result(
        objective=objective_text,
        task_type="patch",
        tool_results=[],
        repo_investigation=investigation,
        artifacts=artifacts,
        review=review,
        workflow_type=WORKFLOW_TYPE,
    )
    review = apply_validation_to_review(review, validation)
    _audit(
        task_id,
        "supervisor",
        "validate_result",
        objective_text,
        f"passed={validation.get('passed')} status={validation.get('final_status')}",
    )

    if not validation.get("passed"):
        target = validation.get("final_status") or TaskLifecycleState.FAILED.value
        target_state = (
            TaskLifecycleState.INSUFFICIENT_EVIDENCE
            if target == "insufficient_evidence"
            else TaskLifecycleState.FAILED
        )
        transition_task_status(
            task_id,
            target_state,
            artifacts_json=artifacts,
            review_json=review,
            error=validation.get("explanation"),
            completed_at=_now_iso(),
            current_step="validation_failed",
        )
        return _detail(task_id)

    risk_score = review.get("risk_score", 50)
    _update_task(
        task_id,
        artifacts_json=artifacts,
        review_json=review,
        approval_required=True,
        approval_status="pending",
        risk_level="high" if risk_score >= 70 else ("medium" if risk_score >= 45 else "low"),
        current_step="waiting_for_approval",
    )

    transition_task_status(task_id, TaskLifecycleState.WAITING_FOR_APPROVAL)
    return _detail(task_id)


def approve_change_task(task_id: str, *, actor_id: str = "dashboard", comment: str = "") -> dict[str, Any]:
    """Approve a Phase 4 change task (does NOT apply patch)."""
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    if row["status"] != TaskLifecycleState.WAITING_FOR_APPROVAL.value:
        raise ValueError(f"task not awaiting approval (status={row['status']})")

    record_approval(task_id=task_id, decision="approved", actor_id=actor_id, comment=comment)
    _update_task(task_id, approval_status="approved")
    _audit(task_id, "service", "approve_change", actor_id, comment or "approved")
    transition_task_status(task_id, TaskLifecycleState.APPROVED, current_step="approved")

    transition_task_status(
        task_id,
        TaskLifecycleState.COMPLETED,
        final_answer="Change approved. Patch NOT applied (Phase 4 — approval only, no write execution).",
        completed_at=_now_iso(),
        current_step="completed",
    )
    return _detail(task_id)


def reject_change_task(task_id: str, *, actor_id: str = "dashboard", comment: str = "") -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    if row["status"] != TaskLifecycleState.WAITING_FOR_APPROVAL.value:
        raise ValueError(f"task not awaiting approval (status={row['status']})")

    record_approval(task_id=task_id, decision="rejected", actor_id=actor_id, comment=comment)
    _audit(task_id, "service", "reject_change", actor_id, comment or "rejected")
    transition_task_status(
        task_id,
        TaskLifecycleState.CANCELLED,
        approval_status="rejected",
        final_answer="Change rejected by approver.",
        completed_at=_now_iso(),
    )
    return _detail(task_id)


def update_change_patch(task_id: str, *, notes: str = "", objective: str | None = None) -> dict[str, Any]:
    """Create a new patch revision for an existing change task."""
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    artifacts = row.get("artifacts") or []
    patch_artifacts = [a for a in artifacts if a.get("standard_name") == "patch.diff" or a.get("name", "").startswith("patch.diff")]
    version = max((a.get("version", 1) for a in patch_artifacts), default=1) + 1

    investigation = {}
    for a in artifacts:
        if a.get("standard_name") == "repository_report.json":
            from app.jarvis.artifacts.storage import load_artifact_content

            import json

            try:
                investigation = json.loads(load_artifact_content(a)).get("investigation", {})
            except (json.JSONDecodeError, TypeError):
                pass

    prev_patch = create_patch(objective=row.get("objective", ""), repository_analysis=investigation)
    new_patch = update_patch(prev_patch, objective=objective, notes=notes)
    review = review_patch(patch=new_patch, repository_analysis=investigation)
    tests = run_tests_for_patch(patch=new_patch, objective=row.get("objective", ""), dry_run=True)
    new_artifacts = _store_phase4_artifacts(
        task_id, patch=new_patch, review=review, tests=tests, repo_report={"investigation": investigation}, version=version
    )
    _update_task(task_id, artifacts_json=[*artifacts, *new_artifacts], review_json=review)
    _audit(task_id, "patch_agent", "update_patch", notes, f"revision={version}")
    return _detail(task_id)


def _safe_approval_status(value: Any) -> str:
    valid = {"not_required", "pending", "approved", "rejected"}
    text = str(value or "pending").strip()
    return text if text in valid else "pending"


def _safe_risk_score(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_review_findings(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    return []


def list_approval_queue(*, limit: int = 20) -> list[dict[str, Any]]:
    """List tasks waiting for approval with patch summary metadata."""
    try:
        tasks = list_execution_tasks(limit=limit)
    except Exception:
        return []
    queue: list[dict[str, Any]] = []
    for task in tasks:
        if task.get("status") not in (
            TaskLifecycleState.WAITING_FOR_APPROVAL.value,
            TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value,
        ):
            continue
        detail = get_execution_task(task["task_id"])
        if detail is None:
            continue
        review = detail.get("review") or {}
        patch_summary = ""
        files_affected: list[str] = []
        for art in detail.get("artifacts") or []:
            if art.get("standard_name") == "patch.diff":
                patch_summary = art.get("preview", "")[:200]
            meta = art.get("metadata") or {}
            if meta.get("patch_id"):
                pass
        for art in detail.get("artifacts") or []:
            if "patch" in art.get("name", ""):
                patch_summary = patch_summary or art.get("preview", "")[:200]
        queue.append(
            {
                "task_id": detail["task_id"],
                "objective": detail.get("objective", ""),
                "status": detail["status"],
                "patch_summary": patch_summary,
                "files_affected": files_affected,
                "risk_score": _safe_risk_score(review.get("risk_score")),
                "test_results": _extract_test_summary(detail),
                "review_findings": _safe_review_findings(review.get("findings", [])),
                "approval_status": _safe_approval_status(detail.get("approval_status")),
                "created_at": detail.get("created_at"),
                "workflow_type": WORKFLOW_TYPE,
                "phase5_available": True,
            }
        )
    return queue


def _extract_test_summary(detail: dict[str, Any]) -> dict[str, Any]:
    for art in detail.get("artifacts") or []:
        if art.get("standard_name") == "tests.json":
            from app.jarvis.artifacts.storage import load_artifact_content

            import json

            try:
                data = json.loads(load_artifact_content(art))
                return data.get("test_report", {})
            except (json.JSONDecodeError, TypeError):
                pass
    return {}


def _detail(task_id: str) -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    row["execution_log"] = list_execution_log(task_id)
    row["approvals"] = list_approvals(task_id)
    row["workflow_type"] = WORKFLOW_TYPE
    return row


def get_change_task_detail(task_id: str) -> dict[str, Any]:
    return _detail(task_id)
