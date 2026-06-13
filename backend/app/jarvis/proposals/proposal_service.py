"""Jarvis Phase 4B patch proposal workflow (backend only; no LLM, no prod writes)."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from app.jarvis.artifacts.storage import create_versioned_artifact
from app.jarvis.execution.audit import list_execution_log, log_execution_event
from app.jarvis.execution.lifecycle import TaskLifecycleState
from app.jarvis.execution.persistence import (
    _update_task,
    create_execution_task,
    get_execution_task,
    transition_task_status,
)
from app.jarvis.investigations.persistence import (
    get_investigation,
    update_investigation_proposal_linkage,
)
from app.jarvis.proposals.config import jarvis_4b_proposals_enabled
from app.jarvis.proposals.eligibility import check_proposal_eligibility, default_eligibility_config
from app.jarvis.proposals.patch_generator import PatchGenerationResult, generate_patch_for_template
from app.jarvis.proposals.sandbox_validation import validate_patch_in_sandbox
from app.services._paths import workspace_root

logger = logging.getLogger(__name__)

WORKFLOW_TYPE = "phase4b_patch_proposal"
PHASE4B_ARTIFACT_NAMES = frozenset(
    {"investigation_context.json", "patch.diff", "tests.json", "review.md"}
)


class ProposalWorkflowError(Exception):
    """Raised when a proposal workflow gate fails."""

    def __init__(self, message: str, *, status_code: int = 400, reasons: list[str] | None = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.reasons = reasons or []


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


def _build_investigation_context(investigation: dict[str, Any], fix_template_id: str) -> dict[str, Any]:
    return {
        "investigation_id": investigation.get("investigation_id"),
        "objective": investigation.get("objective"),
        "category": investigation.get("category"),
        "status": investigation.get("status"),
        "root_cause": investigation.get("root_cause"),
        "confidence": investigation.get("confidence"),
        "recommended_fix": investigation.get("recommended_fix"),
        "impact": investigation.get("impact"),
        "evidence_count": investigation.get("evidence_count", len(investigation.get("evidence") or [])),
        "fix_template_id": fix_template_id,
        "verification_steps": investigation.get("verification_steps") or [],
    }


def _build_tests_json(
    *,
    patch_result: PatchGenerationResult,
    sandbox: dict[str, Any],
    test_paths: list[str],
) -> dict[str, Any]:
    if patch_result.is_noop:
        return {
            "applicable": False,
            "skipped": True,
            "reason": patch_result.reason,
            "test_paths": test_paths,
            "sandbox": sandbox,
        }
    return {
        "applicable": sandbox.get("applicable", False),
        "skipped": sandbox.get("skipped", False),
        "apply_check_passed": sandbox.get("apply_check_passed", False),
        "tests_ran": sandbox.get("tests_ran", False),
        "tests_passed": sandbox.get("tests_passed"),
        "test_paths": test_paths,
        "sandbox": {
            "workdir": sandbox.get("workdir"),
            "error": sandbox.get("error"),
        },
    }


def _build_review_md(
    *,
    investigation: dict[str, Any],
    fix_template_id: str,
    patch_result: PatchGenerationResult,
    sandbox: dict[str, Any],
    tests: dict[str, Any],
) -> str:
    inv_id = investigation.get("investigation_id", "")
    root_cause = investigation.get("root_cause") or ""
    files = patch_result.files_affected

    if patch_result.fix_already_present:
        sandbox_line = "Skipped — fix already present in repository (no patch to apply)."
        recommendation = "No action required. Mark proposal as completed/no_fix_required."
        risks = "- None — existing implementation already addresses the root cause."
    elif sandbox.get("apply_check_passed"):
        sandbox_line = "Passed — `git apply --check` succeeded in isolated sandbox copy."
        if tests.get("tests_ran"):
            passed = tests.get("tests_passed")
            sandbox_line += f" Pytest: {'passed' if passed else 'FAILED'}."
        recommendation = "Approve for human review before any Phase 5 apply/PR workflow."
        risks = (
            "- Trigger-order API may still fail independently; regular orders must remain authoritative.\n"
            "- Verify sync metadata exposes trigger_orders_error_code for observability."
        )
    else:
        sandbox_line = f"Failed — {sandbox.get('error') or 'patch validation failed'}."
        recommendation = "Do not approve. Investigate patch generation or repository state."
        risks = "- Patch does not apply cleanly to current sandbox baseline."

    return (
        f"# Phase 4B Patch Proposal Review\n\n"
        f"## Source investigation\n"
        f"- **ID:** `{inv_id}`\n"
        f"- **Objective:** {investigation.get('objective', '')}\n"
        f"- **Confidence:** {investigation.get('confidence', 0)}%\n\n"
        f"## Root cause\n"
        f"{root_cause}\n\n"
        f"## Fix template\n"
        f"- **ID:** `{fix_template_id}`\n"
        f"- **Strategy:** deterministic template (no LLM)\n"
        f"- **Fix already present:** {patch_result.fix_already_present}\n\n"
        f"## Files affected\n"
        + "".join(f"- `{f}`\n" for f in files)
        + f"\n## Sandbox result\n"
        f"{sandbox_line}\n\n"
        f"## Risks\n"
        f"{risks}\n\n"
        f"## Recommendation\n"
        f"{recommendation}\n"
    )


def _store_proposal_artifacts(
    task_id: str,
    *,
    investigation_context: dict[str, Any],
    patch_content: str,
    tests: dict[str, Any],
    review_md: str,
    patch_metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    meta = patch_metadata or {}
    return [
        create_versioned_artifact(
            task_id=task_id,
            name="investigation_context.json",
            content=investigation_context,
            fmt="json",
            version=1,
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="patch.diff",
            content=patch_content,
            fmt="text",
            version=1,
            metadata=meta,
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="tests.json",
            content=tests,
            fmt="json",
            version=1,
        ),
        create_versioned_artifact(
            task_id=task_id,
            name="review.md",
            content=review_md,
            fmt="markdown",
            version=1,
        ),
    ]


def _detail(task_id: str) -> dict[str, Any]:
    row = get_execution_task(task_id)
    if row is None:
        raise LookupError("task not found")
    plan = row.get("plan") or {}
    row["execution_log"] = list_execution_log(task_id)
    row["workflow_type"] = WORKFLOW_TYPE
    row["source_investigation_id"] = plan.get("source_investigation_id")
    row["fix_template_id"] = plan.get("fix_template_id")
    row["sandbox_summary"] = plan.get("sandbox_summary") or {}
    return row


def _fail_proposal(
    task_id: str,
    investigation_id: str,
    *,
    error: str,
    artifacts: list[dict[str, Any]] | None = None,
    plan_extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    plan = get_execution_task(task_id)
    plan_json = (plan or {}).get("plan") or {}
    if plan_extra:
        plan_json = {**plan_json, **plan_extra}
    _update_task(
        task_id,
        artifacts_json=artifacts or [],
        plan_json=plan_json,
        error=error,
        current_step="failed",
    )
    transition_task_status(
        task_id,
        TaskLifecycleState.FAILED,
        error=error,
        completed_at=_now_iso(),
    )
    update_investigation_proposal_linkage(
        investigation_id,
        proposal_task_id=task_id,
        proposal_status="failed",
    )
    return _detail(task_id)


def submit_patch_proposal(investigation_id: str) -> dict[str, Any]:
    """
    Run the Phase 4B proposal workflow for an eligible investigation.

    Creates a jarvis_task_runs row, generates deterministic artifacts, validates
    in an isolated sandbox copy, and links the investigation proposal fields.
    """
    if not jarvis_4b_proposals_enabled():
        raise ProposalWorkflowError(
            "Phase 4B proposals disabled (JARVIS_4B_PROPOSALS_ENABLED=false)",
            status_code=403,
        )

    inv_id = (investigation_id or "").strip()
    investigation = get_investigation(inv_id)
    if investigation is None:
        raise ProposalWorkflowError("investigation not found", status_code=404)

    eligibility = check_proposal_eligibility(investigation, config=default_eligibility_config())
    if not eligibility.eligible:
        raise ProposalWorkflowError(
            "investigation not eligible for patch proposal",
            status_code=409,
            reasons=eligibility.reasons,
        )

    fix_template = eligibility.fix_template_candidates[0]
    fix_template_id = fix_template["fix_template_id"]
    test_paths = list(fix_template.get("test_paths") or [])

    update_investigation_proposal_linkage(
        inv_id,
        proposal_task_id=None,
        proposal_status="proposing",
    )

    objective = (
        f"Phase 4B patch proposal for investigation {inv_id}: "
        f"{investigation.get('root_cause') or fix_template_id}"
    )
    task_id = str(uuid.uuid4())
    create_execution_task(task_id=task_id, objective=objective, priority="normal", dry_run=True)
    _audit(task_id, "proposal_service", "submit_patch_proposal", inv_id, "queued")

    plan_json: dict[str, Any] = {
        "workflow_type": WORKFLOW_TYPE,
        "source_investigation_id": inv_id,
        "fix_template_id": fix_template_id,
    }
    _update_task(task_id, plan_json=plan_json, current_step="planning")

    transition_task_status(task_id, TaskLifecycleState.PLANNING, started_at=_now_iso())
    transition_task_status(task_id, TaskLifecycleState.INVESTIGATING, current_step="loading_investigation")
    _audit(task_id, "proposal_service", "load_investigation", inv_id, f"template={fix_template_id}")

    repo_root = workspace_root()
    transition_task_status(task_id, TaskLifecycleState.PATCH_READY, current_step="patch_generation")
    try:
        patch_result = generate_patch_for_template(fix_template_id, repo_root=repo_root)
    except (ValueError, FileNotFoundError) as exc:
        return _fail_proposal(task_id, inv_id, error=str(exc))

    investigation_context = _build_investigation_context(investigation, fix_template_id)

    transition_task_status(task_id, TaskLifecycleState.REVIEWING, current_step="sandbox_validation")
    sandbox = validate_patch_in_sandbox(
        task_id=task_id,
        patch_content=patch_result.patch_content,
        test_paths=test_paths,
        is_noop=patch_result.is_noop,
        repo_root=repo_root,
    )
    plan_json["sandbox_summary"] = {
        "applicable": sandbox.get("applicable"),
        "skipped": sandbox.get("skipped"),
        "apply_check_passed": sandbox.get("apply_check_passed"),
        "tests_ran": sandbox.get("tests_ran"),
        "tests_passed": sandbox.get("tests_passed"),
        "error": sandbox.get("error"),
    }

    tests = _build_tests_json(patch_result=patch_result, sandbox=sandbox, test_paths=test_paths)
    review_md = _build_review_md(
        investigation=investigation,
        fix_template_id=fix_template_id,
        patch_result=patch_result,
        sandbox=sandbox,
        tests=tests,
    )

    transition_task_status(task_id, TaskLifecycleState.TESTING, current_step="artifact_storage")
    artifacts = _store_proposal_artifacts(
        task_id,
        investigation_context=investigation_context,
        patch_content=patch_result.patch_content,
        tests=tests,
        review_md=review_md,
        patch_metadata=patch_result.to_dict(),
    )
    _update_task(task_id, artifacts_json=artifacts, plan_json=plan_json)

    # No-op: fix already in repo
    if patch_result.fix_already_present:
        _audit(task_id, "proposal_service", "noop_proposal", inv_id, patch_result.reason[:200])
        transition_task_status(
            task_id,
            TaskLifecycleState.WAITING_FOR_APPROVAL,
            current_step="no_fix_required",
            final_answer="Fix already present — no patch required.",
            approval_required=False,
            approval_status="not_required",
        )
        transition_task_status(task_id, TaskLifecycleState.APPROVED, current_step="approved")
        transition_task_status(
            task_id,
            TaskLifecycleState.COMPLETED,
            completed_at=_now_iso(),
            current_step="completed",
        )
        update_investigation_proposal_linkage(
            inv_id,
            proposal_task_id=task_id,
            proposal_status="no_fix_required",
        )
        return _detail(task_id)

    # Real patch but sandbox failed
    if not sandbox.get("apply_check_passed"):
        return _fail_proposal(
            task_id,
            inv_id,
            error=sandbox.get("error") or "sandbox patch validation failed",
            artifacts=artifacts,
            plan_extra={"sandbox_summary": plan_json["sandbox_summary"]},
        )

    # Optional test failure
    if sandbox.get("tests_ran") and not sandbox.get("tests_passed"):
        return _fail_proposal(
            task_id,
            inv_id,
            error=sandbox.get("error") or "sandbox tests failed",
            artifacts=artifacts,
            plan_extra={"sandbox_summary": plan_json["sandbox_summary"]},
        )

    # Success — awaiting human approval
    _audit(task_id, "proposal_service", "proposal_ready", inv_id, "waiting_for_approval")
    _update_task(
        task_id,
        approval_required=True,
        approval_status="pending",
        current_step="waiting_for_approval",
    )
    transition_task_status(task_id, TaskLifecycleState.WAITING_FOR_APPROVAL)
    update_investigation_proposal_linkage(
        inv_id,
        proposal_task_id=task_id,
        proposal_status="waiting_for_approval",
    )
    return _detail(task_id)


def get_proposal_task_detail(task_id: str) -> dict[str, Any]:
    return _detail(task_id)
