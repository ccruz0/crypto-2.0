"""HTTP API for the Jarvis Bedrock agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.jarvis.mvp.action_plan_persistence import get_action_plan, list_action_plans
from app.jarvis.mvp.action_plan_service import create_action_plan_from_audit
from app.jarvis.mvp.audit_persistence import get_audit_run, list_audit_runs
from app.jarvis.mvp.crypto_audit_persistence import get_crypto_audit_run, list_crypto_audit_runs
from app.jarvis.mvp.decision_analytics import get_decision_analytics
from app.jarvis.mvp.decision_persistence import get_decision, list_decisions
from app.jarvis.mvp.decision_service import create_decision
from app.jarvis.mvp.executive_report_persistence import get_executive_report, list_executive_reports
from app.jarvis.mvp.executive_report_service import create_executive_report
from app.jarvis.mvp.followup_persistence import get_followup, list_followups
from app.jarvis.mvp.followup_service import generate_followups, update_followup_record
from app.jarvis.mvp.initiative_persistence import get_initiative, list_initiatives
from app.jarvis.mvp.initiative_service import create_initiative, update_initiative_record
from app.jarvis.mvp.objective_analytics import get_objective_analytics
from app.jarvis.mvp.objective_persistence import get_objective, list_objectives
from app.jarvis.mvp.objective_service import (
    add_key_result,
    create_objective,
    link_to_objective,
    refresh_objective_metrics,
    seed_sample_objectives,
    update_key_result_record,
    update_objective_record,
)
from app.jarvis.mvp.metrics_persistence import get_executive_dashboard
from app.jarvis.mvp.persistence import get_task_run, list_task_runs
from app.jarvis.mvp.schemas import (
    JarvisActionPlanDetail,
    JarvisActionPlanGenerateRequest,
    JarvisActionPlanListResponse,
    JarvisAuditListResponse,
    JarvisAuditRunDetail,
    JarvisCryptoAuditListResponse,
    JarvisCryptoAuditRunDetail,
    JarvisDecisionCreateRequest,
    JarvisDecisionDetail,
    JarvisDecisionIntelligence,
    JarvisDecisionListResponse,
    JarvisExecutiveDashboardResponse,
    JarvisExecutiveReportDetail,
    JarvisExecutiveReportListResponse,
    JarvisFollowupDetail,
    JarvisFollowupGenerateResponse,
    JarvisFollowupListResponse,
    JarvisFollowupUpdateRequest,
    JarvisInitiativeCreateRequest,
    JarvisInitiativeDetail,
    JarvisInitiativeListResponse,
    JarvisInitiativeUpdateRequest,
    JarvisKeyResultCreateRequest,
    JarvisKeyResultSummary,
    JarvisKeyResultUpdateRequest,
    JarvisKrRefreshResponse,
    JarvisKrRefreshRunsResponse,
    JarvisObjectiveCreateRequest,
    JarvisObjectiveDetail,
    JarvisObjectiveLink,
    JarvisObjectiveLinkRequest,
    JarvisObjectiveListResponse,
    JarvisObjectiveUpdateRequest,
    JarvisTaskListResponse,
    JarvisTaskRequest,
    JarvisTaskResponse,
    JarvisTaskRunDetail,
)
from app.jarvis.execution.schemas import (
    JarvisApprovalQueueResponse,
    JarvisChangeTaskDetail,
    JarvisChangeTaskSubmitRequest,
    JarvisExecutionTaskDetail,
    JarvisExecutionTaskListResponse,
    JarvisInvestigationDetail,
    JarvisInvestigationListResponse,
    JarvisInvestigationPresetsResponse,
    JarvisInvestigationRunRequest,
    JarvisProposalEligibilityResponse,
    JarvisProposalTaskDetail,
    JarvisPatchRevisionRequest,
    JarvisPhase5StatusResponse,
    JarvisTaskApprovalRequest,
    JarvisTaskSubmitRequest,
    JarvisTaskSubmitResponse,
)
from app.jarvis.mvp.service import run_jarvis_task

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jarvis"])


class JarvisRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message for Jarvis")


@router.post("/jarvis")
def jarvis_invoke(body: JarvisRequest) -> dict[str, Any]:
    """Run the Jarvis pipeline (memory → plan → tools) and return structured output."""
    logger.info("jarvis.api.request message_chars=%d", len(body.message or ""))
    try:
        from app.jarvis.orchestrator import run_jarvis
    except Exception as e:
        rid = str(uuid.uuid4())
        logger.exception("jarvis.api.legacy_import_failed jarvis_run_id=%s err=%s", rid, e)
        return {
            "input": body.message,
            "plan": {"error": "legacy_jarvis_import_failed", "detail": str(e)},
            "result": {"error": "legacy_jarvis_unavailable", "detail": str(e)},
            "jarvis_run_id": rid,
        }
    try:
        out = run_jarvis(body.message)
        logger.info("jarvis.api.response jarvis_run_id=%s", out.get("jarvis_run_id"))
        return dict(out)
    except Exception as e:
        rid = str(uuid.uuid4())
        logger.exception("jarvis.api.error jarvis_run_id=%s err=%s", rid, e)
        return {
            "input": body.message,
            "plan": {"error": str(e)},
            "result": {"error": "endpoint_failed", "detail": str(e)},
            "jarvis_run_id": rid,
        }


@router.post("/api/jarvis/task", response_model=JarvisTaskResponse)
def jarvis_task(body: JarvisTaskRequest) -> dict[str, Any]:
    """Run the LangGraph Jarvis MVP pipeline (supervisor → planner → executor → reviewer → cost guard)."""
    logger.info("jarvis.mvp.api.request task_chars=%d dry_run=%s", len(body.task or ""), body.dry_run)
    try:
        out = run_jarvis_task(body.task, dry_run=body.dry_run)
        logger.info(
            "jarvis.mvp.api.response task_id=%s status=%s risk=%s",
            out.get("task_id"),
            out.get("status"),
            out.get("risk_level"),
        )
        return dict(out)
    except Exception as e:
        logger.exception("jarvis.mvp.api.error err=%s", e)
        raise HTTPException(status_code=500, detail=f"jarvis_task_failed: {e}") from e


@router.get("/api/jarvis/tasks", response_model=JarvisTaskListResponse)
def jarvis_task_list(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List recent Jarvis MVP task runs (newest first)."""
    from app.database import engine, ensure_jarvis_task_runs_table

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    tasks = list_task_runs(limit=limit)
    return {"tasks": tasks}


# --- Phase 3: Task execution framework (static paths before /tasks/{task_id}) ---


@router.post("/api/jarvis/tasks/submit", response_model=JarvisTaskSubmitResponse)
def jarvis_execution_submit(body: JarvisTaskSubmitRequest) -> dict[str, Any]:
    """Submit a structured Jarvis execution task (investigation-only by default)."""
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.service import submit_execution_task

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        detail = submit_execution_task(
            objective=body.objective,
            priority=body.priority,
            approval_mode=body.approval_mode,
            dry_run=body.dry_run,
        )
        return {
            "task_id": detail["task_id"],
            "status": detail["status"],
            "objective": detail["objective"],
            "plan": detail.get("plan") or {},
            "approval_required": detail.get("approval_required", False),
            "approval_status": detail.get("approval_status", "not_required"),
            "estimated_cost_usd": detail.get("estimated_cost_usd", 0.0),
            "actual_cost_usd": detail.get("actual_cost_usd", 0.0),
            "current_step": detail.get("current_step"),
            "artifacts": detail.get("artifacts") or [],
            "execution_log": detail.get("execution_log") or [],
        }
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("jarvis.execution.submit_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"jarvis_execution_submit_failed: {exc}") from exc


@router.get("/api/jarvis/tasks/execution", response_model=JarvisExecutionTaskListResponse)
def jarvis_execution_task_list(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.persistence import list_execution_tasks

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"tasks": list_execution_tasks(limit=limit)}


@router.get("/api/jarvis/tasks/execution/{task_id}", response_model=JarvisExecutionTaskDetail)
def jarvis_execution_task_detail(task_id: str) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.service import get_execution_task_detail

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return get_execution_task_detail(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.get("/api/jarvis/tasks/execution/{task_id}/agents")
def jarvis_execution_agent_pipeline(task_id: str) -> dict[str, Any]:
    """Multi-agent operational panel payload derived from task execution log."""
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.agent_pipeline import build_agent_pipeline
    from app.jarvis.execution.service import get_execution_task_detail

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        detail = get_execution_task_detail(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    return build_agent_pipeline(detail)


@router.post("/api/jarvis/tasks/{task_id}/approve", response_model=JarvisExecutionTaskDetail)
def jarvis_execution_approve(task_id: str, body: JarvisTaskApprovalRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.service import approve_task

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return approve_task(task_id, actor_id=body.actor_id, comment=body.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/jarvis/tasks/{task_id}/reject", response_model=JarvisExecutionTaskDetail)
def jarvis_execution_reject(task_id: str, body: JarvisTaskApprovalRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.service import reject_task

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return reject_task(task_id, actor_id=body.actor_id, comment=body.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --- Phase 4A: Production diagnostic investigations (read-only) ---


@router.get("/api/jarvis/investigations/presets", response_model=JarvisInvestigationPresetsResponse)
def jarvis_investigation_presets() -> dict[str, Any]:
    from app.jarvis.investigations.investigation_types import DIAGNOSTIC_PRESETS

    return {"presets": list(DIAGNOSTIC_PRESETS)}


@router.post("/api/jarvis/investigations/run", response_model=JarvisInvestigationDetail)
def jarvis_investigation_run(body: JarvisInvestigationRunRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_investigations_table
    from app.jarvis.investigations.investigation_runner import run_investigation
    from app.jarvis.mvp.config import jarvis_enabled

    if not jarvis_enabled():
        raise HTTPException(status_code=403, detail="Jarvis is disabled (JARVIS_ENABLED=false)")
    if engine is None or not ensure_jarvis_investigations_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        report = run_investigation(body.objective)
        return report.to_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("jarvis.investigation.run_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"jarvis_investigation_run_failed: {exc}") from exc


@router.get("/api/jarvis/investigations", response_model=JarvisInvestigationListResponse)
def jarvis_investigation_list(
    limit: int = Query(default=20, ge=1, le=100),
    q: str = Query(default="", description="Search prior incidents by keyword"),
) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_investigations_table
    from app.jarvis.investigations.investigation_runner import (
        list_investigation_history,
        search_prior_investigations,
    )

    if engine is None or not ensure_jarvis_investigations_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    if q.strip():
        rows = search_prior_investigations(q.strip(), limit=limit)
        investigations = [
            {
                "investigation_id": r.get("investigation_id"),
                "objective": r.get("objective"),
                "status": r.get("status"),
                "root_cause": r.get("root_cause"),
                "confidence": r.get("confidence", 0),
                "evidence_count": r.get("evidence_count", 0),
                "recommended_fix": r.get("recommended_fix"),
                "category": r.get("category"),
                "created_at": r.get("created_at"),
            }
            for r in rows
        ]
    else:
        investigations = list_investigation_history(limit=limit)
    return {"investigations": investigations}


@router.get("/api/jarvis/investigations/{investigation_id}", response_model=JarvisInvestigationDetail)
def jarvis_investigation_detail(investigation_id: str) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_investigations_table
    from app.jarvis.investigations.investigation_runner import get_investigation_detail

    if engine is None or not ensure_jarvis_investigations_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_investigation_detail(investigation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return row


# --- Phase 4B: Patch proposal eligibility (read-only foundation) ---


@router.get(
    "/api/jarvis/proposals/eligibility/{investigation_id}",
    response_model=JarvisProposalEligibilityResponse,
)
def jarvis_proposal_eligibility(investigation_id: str) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_investigations_table
    from app.jarvis.investigations.persistence import get_investigation
    from app.jarvis.proposals.eligibility import check_proposal_eligibility

    if engine is None or not ensure_jarvis_investigations_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_investigation(investigation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="investigation not found")
    return check_proposal_eligibility(row).to_dict()


@router.post(
    "/api/jarvis/investigations/{investigation_id}/propose-patch",
    response_model=JarvisProposalTaskDetail,
)
def jarvis_investigation_propose_patch(investigation_id: str) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_investigations_table, ensure_jarvis_task_runs_table
    from app.jarvis.proposals.proposal_service import ProposalWorkflowError, submit_patch_proposal

    if engine is None or not ensure_jarvis_investigations_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return submit_patch_proposal(investigation_id)
    except ProposalWorkflowError as exc:
        raise HTTPException(
            status_code=exc.status_code,
            detail={"message": exc.message, "reasons": exc.reasons},
        ) from exc
    except Exception as exc:
        logger.exception("jarvis.propose_patch_failed investigation_id=%s err=%s", investigation_id, exc)
        raise HTTPException(status_code=500, detail=f"jarvis_propose_patch_failed: {exc}") from exc


# --- Phase 4: Change workflow (patch generation + review + approval, no application) ---


@router.post("/api/jarvis/tasks/change/submit", response_model=JarvisChangeTaskDetail)
def jarvis_change_submit(body: JarvisChangeTaskSubmitRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.change_service import submit_change_task

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return submit_change_task(
            objective=body.objective,
            priority=body.priority,
            target_files=body.target_files or None,
            dry_run=body.dry_run,
            run_tests=body.run_tests,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("jarvis.change.submit_failed err=%s", exc)
        raise HTTPException(status_code=500, detail=f"jarvis_change_submit_failed: {exc}") from exc


@router.get("/api/jarvis/tasks/change/{task_id}", response_model=JarvisChangeTaskDetail)
def jarvis_change_task_detail(task_id: str) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.change_service import get_change_task_detail

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return get_change_task_detail(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.get("/api/jarvis/approval-queue", response_model=JarvisApprovalQueueResponse)
def jarvis_approval_queue(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    from app.jarvis.execution.change_service import list_approval_queue

    return {"items": list_approval_queue(limit=limit)}


@router.post("/api/jarvis/tasks/change/{task_id}/approve", response_model=JarvisChangeTaskDetail)
def jarvis_change_approve(task_id: str, body: JarvisTaskApprovalRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.change_service import approve_change_task

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return approve_change_task(task_id, actor_id=body.actor_id, comment=body.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/api/jarvis/tasks/change/{task_id}/reject", response_model=JarvisChangeTaskDetail)
def jarvis_change_reject(task_id: str, body: JarvisTaskApprovalRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.change_service import reject_change_task
    from app.jarvis.change_execution.service import reject_change_execution

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        from app.jarvis.execution.persistence import get_execution_task
        from app.jarvis.execution.lifecycle import TaskLifecycleState

        task = get_execution_task(task_id)
        if task and task.get("status") in (
            TaskLifecycleState.WAITING_FOR_PR_APPROVAL.value,
            TaskLifecycleState.APPLYING_PATCH.value,
            TaskLifecycleState.SANDBOX_TESTING.value,
        ):
            return reject_change_execution(task_id, actor_id=body.actor_id, comment=body.comment)
        return reject_change_task(task_id, actor_id=body.actor_id, comment=body.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


# --- Phase 5: Sandbox apply + PR creation ---


@router.post("/api/jarvis/tasks/change/{task_id}/approve-apply", response_model=JarvisChangeTaskDetail)
def jarvis_change_approve_apply(task_id: str, body: JarvisTaskApprovalRequest) -> dict[str, Any]:
    """Gate 1: Approve patch apply in isolated sandbox."""
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.change_execution.service import approve_patch_apply

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return approve_patch_apply(task_id, actor_id=body.actor_id, comment=body.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/api/jarvis/tasks/change/{task_id}/approve-pr", response_model=JarvisChangeTaskDetail)
def jarvis_change_approve_pr(task_id: str, body: JarvisTaskApprovalRequest) -> dict[str, Any]:
    """Gate 2: Approve GitHub PR creation after sandbox tests pass."""
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.change_execution.service import approve_pr_creation

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return approve_pr_creation(task_id, actor_id=body.actor_id, comment=body.comment)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get("/api/jarvis/tasks/change/{task_id}/phase5-status", response_model=JarvisPhase5StatusResponse)
def jarvis_change_phase5_status(task_id: str) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.change_execution.service import get_phase5_status

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return get_phase5_status(task_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.get("/api/jarvis/safety-status")
def jarvis_phase5_safety_status() -> dict[str, Any]:
    from app.jarvis.change_execution.config import phase5_safety_status
    from app.jarvis.proposals.config import phase4b_safety_status

    return {
        "phase4b": phase4b_safety_status(),
        "phase5": phase5_safety_status(),
    }


@router.post("/api/jarvis/tasks/change/{task_id}/patch", response_model=JarvisChangeTaskDetail)
def jarvis_change_patch_revision(task_id: str, body: JarvisPatchRevisionRequest) -> dict[str, Any]:
    from app.database import engine, ensure_jarvis_task_runs_table
    from app.jarvis.execution.change_service import update_change_patch

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    try:
        return update_change_patch(task_id, notes=body.notes, objective=body.objective)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="task not found") from exc


@router.get("/api/jarvis/repository/graph")
def jarvis_repository_graph(refresh: bool = Query(default=False)) -> dict[str, Any]:
    from app.jarvis.repository.persistence import get_repository_metadata, refresh_repository_metadata

    if refresh:
        return refresh_repository_metadata(incremental=True)
    meta = get_repository_metadata()
    if meta is None:
        return refresh_repository_metadata(incremental=False)
    return meta


@router.get("/api/jarvis/github/readonly")
def jarvis_github_readonly() -> dict[str, Any]:
    from app.jarvis.github.integration import github_readonly_summary

    return github_readonly_summary()


@router.get("/api/jarvis/tasks/{task_id}", response_model=JarvisTaskRunDetail)
def jarvis_task_detail(task_id: str) -> dict[str, Any]:
    """Return one Jarvis MVP task run with full detail."""
    from app.database import engine, ensure_jarvis_task_runs_table

    if engine is None or not ensure_jarvis_task_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_task_run(task_id)
    if row is None:
        raise HTTPException(status_code=404, detail="task not found")
    return row


@router.get("/api/jarvis/audits", response_model=JarvisAuditListResponse)
def jarvis_audit_list(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List recent AWS infrastructure audit runs (read-only)."""
    from app.database import engine, ensure_jarvis_audit_runs_table

    if engine is None or not ensure_jarvis_audit_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    audits = list_audit_runs(limit=limit)
    return {"audits": audits}


@router.get("/api/jarvis/audits/{audit_id}", response_model=JarvisAuditRunDetail)
def jarvis_audit_detail(audit_id: str) -> dict[str, Any]:
    """Return one AWS infrastructure audit run with full detail."""
    from app.database import engine, ensure_jarvis_audit_runs_table

    if engine is None or not ensure_jarvis_audit_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_audit_run(audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="audit not found")
    return row


@router.get("/api/jarvis/executive", response_model=JarvisExecutiveDashboardResponse)
def jarvis_executive_dashboard() -> dict[str, Any]:
    """Return executive management dashboard with platform health metrics (read-only)."""
    from app.database import engine, ensure_jarvis_daily_metrics_table

    if engine is None or not ensure_jarvis_daily_metrics_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return get_executive_dashboard()


@router.get("/api/jarvis/crypto-audits", response_model=JarvisCryptoAuditListResponse)
def jarvis_crypto_audit_list(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List recent crypto portfolio audit runs (read-only)."""
    from app.database import engine, ensure_jarvis_crypto_audit_runs_table

    if engine is None or not ensure_jarvis_crypto_audit_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    audits = list_crypto_audit_runs(limit=limit)
    return {"audits": audits}


@router.get("/api/jarvis/crypto-audits/{audit_id}", response_model=JarvisCryptoAuditRunDetail)
def jarvis_crypto_audit_detail(audit_id: str) -> dict[str, Any]:
    """Return one crypto portfolio audit run with full detail."""
    from app.database import engine, ensure_jarvis_crypto_audit_runs_table

    if engine is None or not ensure_jarvis_crypto_audit_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_crypto_audit_run(audit_id)
    if row is None:
        raise HTTPException(status_code=404, detail="crypto audit not found")
    return row


@router.get("/api/jarvis/action-plans", response_model=JarvisActionPlanListResponse)
def jarvis_action_plan_list(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List recent Jarvis action plans (recommendations only, no execution)."""
    from app.database import engine, ensure_jarvis_action_plans_table

    if engine is None or not ensure_jarvis_action_plans_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    plans = list_action_plans(limit=limit)
    return {"plans": plans}


@router.get("/api/jarvis/action-plans/{plan_id}", response_model=JarvisActionPlanDetail)
def jarvis_action_plan_detail(plan_id: str) -> dict[str, Any]:
    """Return one action plan with full remediation recommendations."""
    from app.database import engine, ensure_jarvis_action_plans_table

    if engine is None or not ensure_jarvis_action_plans_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_action_plan(plan_id)
    if row is None:
        raise HTTPException(status_code=404, detail="action plan not found")
    return row


@router.post("/api/jarvis/action-plans/generate", response_model=JarvisActionPlanDetail)
def jarvis_action_plan_generate(body: JarvisActionPlanGenerateRequest) -> dict[str, Any]:
    """Generate a remediation plan from an existing audit (recommendations only)."""
    from app.database import engine, ensure_jarvis_action_plans_table

    if engine is None or not ensure_jarvis_action_plans_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info(
        "jarvis.action_plan.generate source_type=%s source_id=%s",
        body.source_type,
        body.source_id,
    )
    try:
        plan = create_action_plan_from_audit(
            source_type=body.source_type,
            source_id=body.source_id,
        )
        logger.info(
            "jarvis.action_plan.generated plan_id=%s severity=%s status=%s",
            plan.get("plan_id"),
            plan.get("severity"),
            plan.get("status"),
        )
        return plan
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.action_plan.generate_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"action_plan_generate_failed: {e}") from e


@router.get("/api/jarvis/executive-reports", response_model=JarvisExecutiveReportListResponse)
def jarvis_executive_report_list(limit: int = Query(default=20, ge=1, le=100)) -> dict[str, Any]:
    """List recent Chief of Staff weekly priority reports (read-only)."""
    from app.database import engine, ensure_jarvis_executive_reports_table

    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    reports = list_executive_reports(limit=limit)
    return {"reports": reports}


@router.get("/api/jarvis/executive-reports/{report_id}", response_model=JarvisExecutiveReportDetail)
def jarvis_executive_report_detail(report_id: str) -> dict[str, Any]:
    """Return one executive priorities report with full detail."""
    from app.database import engine, ensure_jarvis_executive_reports_table

    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_executive_report(report_id)
    if row is None:
        raise HTTPException(status_code=404, detail="executive report not found")
    return row


@router.post("/api/jarvis/executive-reports/generate", response_model=JarvisExecutiveReportDetail)
def jarvis_executive_report_generate() -> dict[str, Any]:
    """Generate a weekly priorities report from current audit and metrics data (read-only)."""
    from app.database import engine, ensure_jarvis_executive_reports_table

    if engine is None or not ensure_jarvis_executive_reports_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.executive_report.generate requested")
    try:
        report = create_executive_report(skip_if_recent=False, send_telegram=True)
        logger.info(
            "jarvis.executive_report.generated report_id=%s health_score=%s",
            report.get("report_id"),
            report.get("overall_health_score"),
        )
        return report
    except Exception as e:
        logger.exception("jarvis.executive_report.generate_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"executive_report_generate_failed: {e}") from e


@router.post("/api/jarvis/decisions", response_model=JarvisDecisionDetail)
def jarvis_decision_create(body: JarvisDecisionCreateRequest) -> dict[str, Any]:
    """Record a human decision on a recommendation (no execution performed)."""
    from app.database import engine, ensure_jarvis_decisions_table

    if engine is None or not ensure_jarvis_decisions_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info(
        "jarvis.decision.create decision=%s source_type=%s plan_id=%s",
        body.decision,
        body.source_type,
        body.plan_id,
    )
    try:
        stored = create_decision(
            source_type=body.source_type,
            source_id=body.source_id,
            plan_id=body.plan_id,
            decision=body.decision,
            decision_reason=body.decision_reason,
            outcome=body.outcome,
            reviewed_by=body.reviewed_by,
        )
        return stored
    except Exception as e:
        logger.exception("jarvis.decision.create_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"decision_create_failed: {e}") from e


@router.get("/api/jarvis/decisions", response_model=JarvisDecisionListResponse)
def jarvis_decision_list(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    """List Jarvis decision records (newest first)."""
    from app.database import engine, ensure_jarvis_decisions_table

    if engine is None or not ensure_jarvis_decisions_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    decisions = list_decisions(limit=limit)
    return {"decisions": decisions}


@router.get("/api/jarvis/decisions/{decision_id}", response_model=JarvisDecisionDetail)
def jarvis_decision_detail(decision_id: str) -> dict[str, Any]:
    """Return one decision record with full detail."""
    from app.database import engine, ensure_jarvis_decisions_table

    if engine is None or not ensure_jarvis_decisions_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_decision(decision_id)
    if row is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return row


@router.get("/api/jarvis/decision-analytics", response_model=JarvisDecisionIntelligence)
def jarvis_decision_analytics() -> dict[str, Any]:
    """Return decision intelligence analytics (read-only)."""
    from app.database import engine, ensure_jarvis_decisions_table

    if engine is None or not ensure_jarvis_decisions_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return get_decision_analytics()


@router.post("/api/jarvis/initiatives", response_model=JarvisInitiativeDetail)
def jarvis_initiative_create(body: JarvisInitiativeCreateRequest) -> dict[str, Any]:
    """Create a new initiative (human-controlled management layer, no execution)."""
    from app.database import engine, ensure_jarvis_initiatives_table

    if engine is None or not ensure_jarvis_initiatives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.initiative.create title=%s status=%s", body.title, body.status)
    try:
        stored = create_initiative(
            title=body.title,
            description=body.description,
            status=body.status,
            priority=body.priority,
            owner=body.owner,
            target_date=body.target_date,
            source_type=body.source_type,
            source_id=body.source_id,
            progress_pct=body.progress_pct,
            blocked_reason=body.blocked_reason,
        )
        return stored
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.initiative.create_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"initiative_create_failed: {e}") from e


@router.get("/api/jarvis/initiatives", response_model=JarvisInitiativeListResponse)
def jarvis_initiative_list(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    """List Jarvis initiatives (newest updated first)."""
    from app.database import engine, ensure_jarvis_initiatives_table

    if engine is None or not ensure_jarvis_initiatives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    initiatives = list_initiatives(limit=limit, status=status)
    return {"initiatives": initiatives}


@router.get("/api/jarvis/initiatives/{initiative_id}", response_model=JarvisInitiativeDetail)
def jarvis_initiative_detail(initiative_id: str) -> dict[str, Any]:
    """Return one initiative with full detail."""
    from app.database import engine, ensure_jarvis_initiatives_table

    if engine is None or not ensure_jarvis_initiatives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_initiative(initiative_id)
    if row is None:
        raise HTTPException(status_code=404, detail="initiative not found")
    return row


@router.put("/api/jarvis/initiatives/{initiative_id}", response_model=JarvisInitiativeDetail)
def jarvis_initiative_update(initiative_id: str, body: JarvisInitiativeUpdateRequest) -> dict[str, Any]:
    """Update an initiative (recalculates health automatically)."""
    from app.database import engine, ensure_jarvis_initiatives_table

    if engine is None or not ensure_jarvis_initiatives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.initiative.update initiative_id=%s", initiative_id)
    try:
        stored = update_initiative_record(
            initiative_id=initiative_id,
            title=body.title,
            description=body.description,
            status=body.status,
            priority=body.priority,
            owner=body.owner,
            target_date=body.target_date,
            source_type=body.source_type,
            source_id=body.source_id,
            progress_pct=body.progress_pct,
            blocked_reason=body.blocked_reason,
        )
        return stored
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.initiative.update_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"initiative_update_failed: {e}") from e


@router.post("/api/jarvis/followups/generate", response_model=JarvisFollowupGenerateResponse)
def jarvis_followup_generate(send_telegram: bool = Query(default=True)) -> dict[str, Any]:
    """Detect and upsert follow-up reminders (read-only, no execution)."""
    from app.database import engine, ensure_jarvis_followups_table

    if engine is None or not ensure_jarvis_followups_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.followup.generate send_telegram=%s", send_telegram)
    try:
        result = generate_followups(send_telegram=send_telegram)
        logger.info(
            "jarvis.followup.generated touched=%s telegram_sent=%s",
            result.get("followups_touched"),
            result.get("telegram_sent"),
        )
        return result
    except Exception as e:
        logger.exception("jarvis.followup.generate_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"followup_generate_failed: {e}") from e


@router.get("/api/jarvis/followups", response_model=JarvisFollowupListResponse)
def jarvis_followup_list(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
    severity: str | None = Query(default=None),
) -> dict[str, Any]:
    """List Jarvis follow-up reminders."""
    from app.database import engine, ensure_jarvis_followups_table

    if engine is None or not ensure_jarvis_followups_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    followups = list_followups(limit=limit, status=status, severity=severity)
    return {"followups": followups}


@router.get("/api/jarvis/followups/{followup_id}", response_model=JarvisFollowupDetail)
def jarvis_followup_detail(followup_id: str) -> dict[str, Any]:
    """Return one follow-up reminder with full detail."""
    from app.database import engine, ensure_jarvis_followups_table

    if engine is None or not ensure_jarvis_followups_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_followup(followup_id)
    if row is None:
        raise HTTPException(status_code=404, detail="followup not found")
    return row


@router.put("/api/jarvis/followups/{followup_id}", response_model=JarvisFollowupDetail)
def jarvis_followup_update(followup_id: str, body: JarvisFollowupUpdateRequest) -> dict[str, Any]:
    """Update follow-up status (acknowledge, resolve, dismiss)."""
    from app.database import engine, ensure_jarvis_followups_table

    if engine is None or not ensure_jarvis_followups_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.followup.update followup_id=%s status=%s", followup_id, body.status)
    try:
        stored = update_followup_record(
            followup_id=followup_id,
            status=body.status,
            severity=body.severity,
            assigned_to=body.assigned_to,
            description=body.description,
        )
        return stored
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.followup.update_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"followup_update_failed: {e}") from e


@router.post("/api/jarvis/objectives", response_model=JarvisObjectiveDetail)
def jarvis_objective_create(body: JarvisObjectiveCreateRequest) -> dict[str, Any]:
    """Create a strategic objective (read-only management, no execution)."""
    from app.database import engine, ensure_jarvis_objectives_table

    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.objective.create title=%s status=%s", body.title, body.status)
    try:
        return create_objective(
            title=body.title,
            description=body.description,
            status=body.status,
            owner=body.owner,
            target_date=body.target_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.objective.create_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"objective_create_failed: {e}") from e


@router.get("/api/jarvis/objectives", response_model=JarvisObjectiveListResponse)
def jarvis_objective_list(
    limit: int = Query(default=50, ge=1, le=200),
    status: str | None = Query(default=None),
) -> dict[str, Any]:
    """List strategic objectives."""
    from app.database import engine, ensure_jarvis_objectives_table
    from app.jarvis.mvp.objective_persistence import list_all_objectives

    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    if status:
        objectives = list_objectives(limit=limit, status=status)
    else:
        objectives = list_all_objectives()[:limit]
    return {"objectives": objectives}


@router.get("/api/jarvis/objectives/{objective_id}", response_model=JarvisObjectiveDetail)
def jarvis_objective_detail(objective_id: str) -> dict[str, Any]:
    """Return one objective with key results, links, and trend."""
    from app.database import engine, ensure_jarvis_objectives_table

    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    row = get_objective(objective_id)
    if row is None:
        raise HTTPException(status_code=404, detail="objective not found")
    return row


@router.put("/api/jarvis/objectives/{objective_id}", response_model=JarvisObjectiveDetail)
def jarvis_objective_update(objective_id: str, body: JarvisObjectiveUpdateRequest) -> dict[str, Any]:
    """Update a strategic objective."""
    from app.database import engine, ensure_jarvis_objectives_table

    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    logger.info("jarvis.objective.update objective_id=%s", objective_id)
    try:
        return update_objective_record(
            objective_id=objective_id,
            title=body.title,
            description=body.description,
            status=body.status,
            owner=body.owner,
            target_date=body.target_date,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.objective.update_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"objective_update_failed: {e}") from e


@router.post("/api/jarvis/objectives/{objective_id}/key-results", response_model=JarvisKeyResultSummary)
def jarvis_key_result_create(objective_id: str, body: JarvisKeyResultCreateRequest) -> dict[str, Any]:
    """Add a measurable key result to an objective."""
    from app.database import engine, ensure_jarvis_key_results_table

    if engine is None or not ensure_jarvis_key_results_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        return add_key_result(
            objective_id=objective_id,
            title=body.title,
            metric_name=body.metric_name,
            target_value=body.target_value,
            current_value=body.current_value,
            unit=body.unit,
            direction=body.direction,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.key_result.create_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"key_result_create_failed: {e}") from e


@router.put("/api/jarvis/objectives/key-results/{kr_id}", response_model=JarvisKeyResultSummary)
def jarvis_key_result_update(kr_id: str, body: JarvisKeyResultUpdateRequest) -> dict[str, Any]:
    """Update key result current or target value."""
    from app.database import engine, ensure_jarvis_key_results_table

    if engine is None or not ensure_jarvis_key_results_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        return update_key_result_record(
            kr_id=kr_id,
            title=body.title,
            current_value=body.current_value,
            target_value=body.target_value,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.key_result.update_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"key_result_update_failed: {e}") from e


@router.post("/api/jarvis/objectives/{objective_id}/links", response_model=JarvisObjectiveLink)
def jarvis_objective_link_create(objective_id: str, body: JarvisObjectiveLinkRequest) -> dict[str, Any]:
    """Link an objective to an initiative, audit, plan, decision, or report."""
    from app.database import engine, ensure_jarvis_objective_links_table

    if engine is None or not ensure_jarvis_objective_links_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")

    try:
        return link_to_objective(
            objective_id=objective_id,
            linked_type=body.linked_type,
            linked_id=body.linked_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except Exception as e:
        logger.exception("jarvis.objective.link_failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"objective_link_failed: {e}") from e


@router.post("/api/jarvis/objectives/seed")
def jarvis_objectives_seed() -> dict[str, Any]:
    """Create sample objectives for validation (idempotent)."""
    from app.database import engine, ensure_jarvis_objectives_table

    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return seed_sample_objectives()


@router.post("/api/jarvis/objectives/metrics/refresh")
def jarvis_objectives_metrics_refresh() -> dict[str, Any]:
    """Record objective metric snapshots for trend charts."""
    from app.database import engine, ensure_jarvis_objective_metrics_table

    if engine is None or not ensure_jarvis_objective_metrics_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return refresh_objective_metrics()


@router.post("/api/jarvis/objectives/key-results/refresh", response_model=JarvisKrRefreshResponse)
def jarvis_key_results_refresh() -> dict[str, Any]:
    """Refresh KR current_value from read-only live metrics (no execution)."""
    from app.database import engine, ensure_jarvis_key_results_table, ensure_jarvis_kr_refresh_runs_table

    if engine is None or not ensure_jarvis_key_results_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    if not ensure_jarvis_kr_refresh_runs_table(engine):
        raise HTTPException(status_code=503, detail="KR refresh persistence unavailable")

    logger.info("jarvis.kr_refresh.start")
    try:
        from app.jarvis.mvp.kr_refresh_service import refresh_key_results

        return refresh_key_results(send_telegram=True)
    except Exception as e:
        logger.exception("jarvis.kr_refresh.failed err=%s", e)
        raise HTTPException(status_code=500, detail=f"kr_refresh_failed: {e}") from e


@router.get("/api/jarvis/objectives/key-results/refresh-runs", response_model=JarvisKrRefreshRunsResponse)
def jarvis_key_results_refresh_runs(
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """List recent KR metric refresh runs."""
    from app.database import engine, ensure_jarvis_kr_refresh_runs_table
    from app.jarvis.mvp.kr_refresh_persistence import list_kr_refresh_runs

    if engine is None or not ensure_jarvis_kr_refresh_runs_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return {"runs": list_kr_refresh_runs(limit=limit), "read_only": True}


@router.get("/api/jarvis/objective-analytics")
def jarvis_objective_analytics() -> dict[str, Any]:
    """Return objective intelligence analytics (read-only)."""
    from app.database import engine, ensure_jarvis_objectives_table

    if engine is None or not ensure_jarvis_objectives_table(engine):
        raise HTTPException(status_code=503, detail="Database unavailable")
    return get_objective_analytics()
