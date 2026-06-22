"""Autonomous Coding Workflow orchestrator — LAB-only objective-to-PR pipeline."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.core.environment import is_atp_trading_only, is_jarvis_builder_allowed
from app.jarvis.agents.planner_agent import build_plan, plan_to_dict
from app.jarvis.agents.reviewer_agent import review_patch
from app.jarvis.agents.test_agent import run_tests_for_patch
from app.jarvis.artifacts.storage import create_versioned_artifact, load_artifact_content
from app.jarvis.change_execution.config import (
    jarvis_github_write_enabled,
    jarvis_patch_apply_enabled,
    jarvis_pr_creation_enabled,
    jarvis_require_double_approval,
)
from app.jarvis.change_execution.forbidden_paths import check_forbidden_paths
from app.jarvis.coding_workflow.evidence import collect_acw_evidence, evidence_summary
from app.jarvis.coding_workflow.patch_bridge import PlaceholderPatchError, generate_patch_via_bridge
from app.jarvis.coding_workflow.schemas import WORKFLOW_TYPE
from app.jarvis.execution.audit import list_execution_log, log_execution_event
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    create_execution_task,
    get_execution_task,
    list_approvals,
    list_execution_tasks,
    transition_task_status,
)
from app.jarvis.execution.safety import SafetyLevel, classify_change_objective, is_forbidden
from app.jarvis.mvp.config import jarvis_enabled
from app.services.cursor_execution_bridge import (
    CursorAuthMissingError,
    is_bridge_enabled,
    require_cursor_auth,
)

logger = logging.getLogger(__name__)


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


def check_acw_submit_allowed() -> None:
    """Fail closed when LAB prerequisites for ACW submit are not met."""
    if is_atp_trading_only():
        raise RuntimeError("ACW blocked: ATP_TRADING_ONLY=1 (LAB only)")
    if not jarvis_enabled():
        raise RuntimeError("Jarvis is disabled (JARVIS_ENABLED=false)")
    if not is_jarvis_builder_allowed():
        raise RuntimeError("ACW blocked: JARVIS_BUILDER_ALLOWED not enabled (LAB only)")
    if not is_bridge_enabled():
        raise RuntimeError("ACW blocked: CURSOR_BRIDGE_ENABLED not enabled")
    require_cursor_auth()


def _parse_files_from_diff(diff: str) -> list[str]:
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            path = line[6:].strip()
            if path and path != "/dev/null":
                files.append(path)
    return files


def _build_approval_package(
    *,
    task_id: str,
    objective: str,
    plan: dict[str, Any],
    evidence: dict[str, Any],
    patch: dict[str, Any],
    review: dict[str, Any],
    forbidden_check: dict[str, Any],
) -> dict[str, Any]:
    diff = patch.get("unified_diff", "")
    files = patch.get("target_files") or _parse_files_from_diff(diff)
    pr_eligible = (
        jarvis_patch_apply_enabled()
        and jarvis_pr_creation_enabled()
        and jarvis_github_write_enabled()
        and forbidden_check.get("passed", True)
    )
    required = ["gate1_apply"]
    if jarvis_require_double_approval():
        required.append("gate2_pr")

    return {
        "objective": objective,
        "task_id": task_id,
        "workflow_type": WORKFLOW_TYPE,
        "plan": plan,
        "evidence_summary": evidence_summary(evidence),
        "patch_diff_summary": f"{len(files)} file(s), {len(diff)} bytes — {patch.get('patch_summary', '')[:200]}",
        "full_patch_artifact": "patch.diff",
        "risk_score": review.get("risk_score", patch.get("risk_assessment", {}).get("risk_score", 50)),
        "forbidden_path_check": forbidden_check,
        "sandbox_test_results": None,
        "required_approvals": required,
        "pr_creation_eligible": pr_eligible,
    }


def _store_acw_artifacts(
    task_id: str,
    *,
    patch: dict[str, Any],
    review: dict[str, Any],
    tests: dict[str, Any],
    evidence: dict[str, Any],
    approval_package: dict[str, Any],
    version: int = 1,
) -> list[dict[str, Any]]:
    return [
        create_versioned_artifact(
            task_id=task_id,
            name="patch.diff",
            content=patch.get("unified_diff", ""),
            fmt="text",
            version=version,
            metadata={
                "patch_id": patch.get("patch_id"),
                "source": patch.get("source", "cursor_bridge"),
                "risk_score": patch.get("risk_assessment", {}).get("risk_score"),
                "generation_attempts": patch.get("generation_attempts"),
                "retry_used": patch.get("retry_used"),
                "retry_reason": patch.get("retry_reason"),
            },
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
            name="evidence.json",
            content=evidence,
            fmt="json",
            version=version,
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="approval_package.json",
            content=approval_package,
            fmt="json",
            version=version,
        ),
    ]


def submit_coding_workflow(
    *,
    objective: str,
    priority: str = "normal",
    target_files: list[str] | None = None,
) -> dict[str, Any]:
    """
    Run ACW pipeline: objective → plan → evidence → Cursor patch → review → approval package.

    Patch apply and PR creation happen only after Gate 1 / Gate 2 approvals.
    """
    check_acw_submit_allowed()

    objective_text = (objective or "").strip()
    if not objective_text:
        raise ValueError("objective is required")

    if is_forbidden(classify_change_objective(objective_text)):
        task_id = str(uuid.uuid4())
        create_execution_task(task_id=task_id, objective=objective_text, priority=priority, dry_run=True)
        _audit(task_id, "acw", "submit", objective_text, "FORBIDDEN objective")
        transition_task_status(task_id, TaskLifecycleState.PLANNING, started_at=_now_iso())
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error="Objective classified as FORBIDDEN",
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    task_id = str(uuid.uuid4())
    create_execution_task(task_id=task_id, objective=objective_text, priority=priority, dry_run=True)
    _audit(task_id, "acw", "submit", objective_text, "queued")
    _update_task(task_id, current_step="planning", plan_json={"workflow_type": WORKFLOW_TYPE})

    transition_task_status(task_id, TaskLifecycleState.PLANNING, started_at=_now_iso())
    plan = build_plan(objective_text)
    plan_dict = plan_to_dict(plan)
    plan_dict["workflow_type"] = WORKFLOW_TYPE
    plan_dict["acw"] = {"gates": ["gate1_apply", "gate2_pr"], "lab_only": True}
    _update_task(task_id, plan_json=plan_dict, estimated_cost_usd=plan.total_estimated_cost_usd)
    _audit(task_id, "planner_agent", "build_plan", objective_text, f"steps={len(plan.steps)}")

    transition_task_status(task_id, TaskLifecycleState.INVESTIGATING, current_step="evidence_collection")
    evidence = collect_acw_evidence(objective_text, target_files=target_files)
    _audit(
        task_id,
        "acw",
        "collect_evidence",
        objective_text,
        f"refs={len(evidence.get('code_references', []))} prod={len(evidence.get('production_evidence', []))}",
    )

    transition_task_status(task_id, TaskLifecycleState.PATCH_READY, current_step="patch_generation")
    try:
        patch = generate_patch_via_bridge(
            task_id,
            objective=objective_text,
            plan=plan_dict,
            evidence=evidence,
            target_files=target_files,
        )
    except PlaceholderPatchError as exc:
        _audit(task_id, "patch_bridge", "generate_patch", objective_text, f"PLACEHOLDER: {exc}")
        if exc.retry_used:
            _audit(
                task_id,
                "patch_bridge",
                "generate_patch_retry",
                objective_text,
                f"attempts={exc.generation_attempts} reason={(exc.retry_reason or '')[:200]}",
            )
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error=f"Placeholder or invalid patch rejected: {exc}",
            completed_at=_now_iso(),
        )
        detail = _detail(task_id)
        detail["patch_generation"] = {
            "generation_attempts": exc.generation_attempts,
            "retry_used": exc.retry_used,
            "retry_reason": exc.retry_reason,
        }
        return detail
    except CursorAuthMissingError as exc:
        _audit(task_id, "patch_bridge", "generate_patch", objective_text, exc.error_info["code"])
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error=exc.error_info["cause"],
            completed_at=_now_iso(),
        )
        detail = _detail(task_id)
        detail["cursor_auth_error"] = exc.error_info
        return detail
    except RuntimeError as exc:
        _audit(task_id, "patch_bridge", "generate_patch", objective_text, f"FAILED: {exc}")
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error=str(exc),
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    _audit(task_id, "patch_bridge", "generate_patch", objective_text, patch.get("patch_summary", "")[:200])
    if patch.get("retry_used"):
        _audit(
            task_id,
            "patch_bridge",
            "generate_patch_retry",
            objective_text,
            f"attempts={patch.get('generation_attempts')} reason={patch.get('retry_reason', '')[:200]}",
        )

    changed_files = patch.get("target_files") or _parse_files_from_diff(patch.get("unified_diff", ""))
    forbidden_check = check_forbidden_paths(changed_files)

    transition_task_status(task_id, TaskLifecycleState.REVIEWING, current_step="reviewing")
    review = review_patch(patch=patch, repository_analysis=evidence.get("investigation", {}))
    if not forbidden_check.get("passed", True):
        review["findings"] = list(review.get("findings") or []) + [
            {
                "dimension": "policy",
                "finding": f"forbidden paths in patch: {forbidden_check.get('blocked_paths', [])}",
                "severity": "high",
            }
        ]
        review["risk_score"] = min(100, int(review.get("risk_score", 50)) + 30)
        review["approval_recommendation"] = "reject"
    _audit(task_id, "reviewer_agent", "review_patch", patch.get("patch_id", ""), f"risk={review.get('risk_score')}")

    transition_task_status(task_id, TaskLifecycleState.TESTING, current_step="dry_run_tests")
    test_result = run_tests_for_patch(patch=patch, objective=objective_text, dry_run=True)
    _audit(task_id, "test_agent", "run_tests", objective_text, test_result.get("summary", ""))

    if not forbidden_check.get("passed", True):
        _audit(task_id, "acw", "forbidden_paths", objective_text, str(forbidden_check.get("blocked_paths")))
        transition_task_status(
            task_id,
            TaskLifecycleState.FAILED,
            error=f"Patch touches forbidden paths: {forbidden_check.get('blocked_paths')}",
            completed_at=_now_iso(),
        )
        return _detail(task_id)

    approval_package = _build_approval_package(
        task_id=task_id,
        objective=objective_text,
        plan=plan_dict,
        evidence=evidence,
        patch=patch,
        review=review,
        forbidden_check=forbidden_check,
    )

    artifacts = _store_acw_artifacts(
        task_id,
        patch=patch,
        review=review,
        tests=test_result,
        evidence=evidence,
        approval_package=approval_package,
    )

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
    _audit(task_id, "acw", "approval_package_ready", objective_text, f"artifacts={len(artifacts)}")
    return _detail(task_id)


def is_coding_workflow_task(task: dict[str, Any]) -> bool:
    plan = task.get("plan") or {}
    return plan.get("workflow_type") == WORKFLOW_TYPE


def list_coding_workflow_queue_items(*, limit: int = 20) -> list[dict[str, Any]]:
    """Approval queue entries for ACW tasks."""
    items: list[dict[str, Any]] = []
    for task in list_execution_tasks(limit=limit * 3):
        detail = get_execution_task(task["task_id"])
        if detail is None or not is_coding_workflow_task(detail):
            continue
        if detail.get("status") not in (
            TaskLifecycleState.WAITING_FOR_APPROVAL.value,
            TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value,
        ):
            continue
        review = detail.get("review") or {}
        patch_summary = ""
        for art in detail.get("artifacts") or []:
            if art.get("standard_name") == "patch.diff" or str(art.get("name", "")).startswith("patch.diff"):
                patch_summary = str(art.get("preview", ""))[:200]
        items.append(
            {
                "task_id": detail["task_id"],
                "objective": detail.get("objective", ""),
                "status": detail["status"],
                "patch_summary": patch_summary,
                "files_affected": [],
                "risk_score": review.get("risk_score"),
                "test_results": _extract_test_summary(detail),
                "review_findings": review.get("findings", []),
                "approval_status": detail.get("approval_status"),
                "created_at": detail.get("created_at"),
                "workflow_type": WORKFLOW_TYPE,
                "phase5_available": True,
            }
        )
        if len(items) >= limit:
            break
    return items


def _extract_test_summary(detail: dict[str, Any]) -> dict[str, Any]:
    for art in detail.get("artifacts") or []:
        if art.get("standard_name") == "tests.json":
            import json

            try:
                data = json.loads(load_artifact_content(art))
                return data.get("test_report", {})
            except (json.JSONDecodeError, TypeError, OSError):
                pass
    return {}


def _load_approval_package(task: dict[str, Any]) -> dict[str, Any]:
    for art in task.get("artifacts") or []:
        if art.get("standard_name") == "approval_package.json" or art.get("name") == "approval_package.json":
            import json

            try:
                return json.loads(load_artifact_content(art))
            except (json.JSONDecodeError, TypeError, OSError):
                pass
    return {}


def _detail(task_id: str) -> dict[str, Any]:
    from app.jarvis.change_execution.service import get_phase5_status

    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    row["execution_log"] = list_execution_log(task_id)
    row["approvals"] = list_approvals(task_id)
    row["workflow_type"] = WORKFLOW_TYPE
    row["approval_package"] = _load_approval_package(row)
    try:
        row["phase5"] = get_phase5_status(task_id)
    except LookupError:
        row["phase5"] = {}
    return row


def get_coding_workflow_detail(task_id: str) -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    if not is_coding_workflow_task(row):
        raise LookupError("not a coding workflow task")
    return _detail(task_id)


def get_coding_workflow_artifacts(task_id: str) -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    if not is_coding_workflow_task(row):
        raise LookupError("not a coding workflow task")
    return {"task_id": task_id, "artifacts": row.get("artifacts") or []}
