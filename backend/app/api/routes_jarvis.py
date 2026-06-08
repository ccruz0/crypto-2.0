"""HTTP API for the Jarvis Bedrock agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

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
from app.jarvis.mvp.schemas import (
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
from app.jarvis.mvp.persistence import get_task_run, list_task_runs
from app.jarvis.mvp.schemas import (
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
from app.jarvis.mvp.service import run_jarvis_task
from app.jarvis.orchestrator import run_jarvis

logger = logging.getLogger(__name__)

router = APIRouter(tags=["jarvis"])


class JarvisRequest(BaseModel):
    message: str = Field(..., min_length=1, description="User message for Jarvis")


@router.post("/jarvis")
def jarvis_invoke(body: JarvisRequest) -> dict[str, Any]:
    """Run the Jarvis pipeline (memory → plan → tools) and return structured output."""
    logger.info("jarvis.api.request message_chars=%d", len(body.message or ""))
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
