"""End-to-end Jarvis pipeline: memory → plan → execute → memory."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.jarvis.executor import execute_plan
from app.jarvis.memory import JarvisMemory, get_default_memory
from app.jarvis.planner import create_plan
from app.jarvis.plan_validation import PlanValidated
from app.jarvis.schemas import JarvisRunResult

logger = logging.getLogger(__name__)


def run_jarvis(user_input: str, *, memory: JarvisMemory | None = None) -> JarvisRunResult:
    """
    1. Load recent context from memory
    2. Create plan via Bedrock
    3. Execute plan
    4. Persist interaction
    5. Return structured response (includes ``jarvis_run_id`` for tracing)
    """
    jarvis_run_id = str(uuid.uuid4())
    text = (user_input or "").strip()
    logger.info("jarvis.run start run_id=%s input_chars=%d", jarvis_run_id, len(text))
    out: JarvisRunResult = {
        "input": text,
        "plan": {},
        "result": None,
        "jarvis_run_id": jarvis_run_id,
    }

    mem = memory or get_default_memory()

    try:
        context = mem.get_recent_context()
    except Exception as e:
        logger.exception("jarvis.run memory_context_failed run_id=%s err=%s", jarvis_run_id, e)
        context = ""

    try:
        plan = create_plan(text, recent_context=context, jarvis_run_id=jarvis_run_id)
        if not isinstance(plan, dict):
            p = PlanValidated(
                action="echo_message",
                args={"message": text[:500]},
                reasoning="invalid plan type from planner",
            )
            plan = p.model_dump()
    except Exception as e:
        logger.exception("jarvis.run create_plan_failed run_id=%s err=%s", jarvis_run_id, e)
        p = PlanValidated(
            action="echo_message",
            args={"message": f"[error] {text[:500]}"},
            reasoning=f"create_plan exception: {e!s}",
        )
        plan = p.model_dump()

    out["plan"] = plan

    try:
        result = execute_plan(plan, jarvis_run_id=jarvis_run_id)
    except Exception as e:
        logger.exception("jarvis.run execute_failed run_id=%s err=%s", jarvis_run_id, e)
        result = {"error": "execute_failed", "detail": str(e)}

    out["result"] = result

    try:
        mem.save_interaction(text, result)
    except Exception as e:
        logger.exception("jarvis.run save_interaction_failed run_id=%s err=%s", jarvis_run_id, e)

    logger.info("jarvis.run done run_id=%s", jarvis_run_id)
    return out
