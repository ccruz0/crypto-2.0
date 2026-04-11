"""HTTP API for the Jarvis Bedrock agent."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

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
