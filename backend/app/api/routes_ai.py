"""
AI Engine API routes. Scaffold only; no model calls. Optional tool_calls logged to tools.json.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Optional

from app.services.ai_engine.engine import run_ai_task

router = APIRouter(prefix="/api/ai", tags=["ai"])


class AIRunRequest(BaseModel):
    task: str
    mode: str = "sandbox"
    apply_changes: bool = False
    tool_calls: Optional[list[dict[str, Any]]] = None


@router.post("/run")
def ai_run(payload: AIRunRequest):
    """Run AI task (scaffold: audit logging; optional tool_calls run and logged to tools.json)."""
    try:
        body = payload.model_dump()
        if body.get("tool_calls") is None:
            body.pop("tool_calls", None)
        result = run_ai_task(body)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
