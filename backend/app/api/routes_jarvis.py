"""HTTP API for the Jarvis Bedrock agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.jarvis.mvp.persistence import get_task_run, list_task_runs
from app.jarvis.mvp.schemas import (
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
