"""Jarvis LangGraph MVP task execution service."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.jarvis.mvp.config import jarvis_dry_run_only, jarvis_enabled
from app.jarvis.mvp.graph import get_jarvis_graph
from app.jarvis.mvp.persistence import record_task_completed, record_task_started
from app.jarvis.mvp.risk import classify_task_risk

logger = logging.getLogger(__name__)


def _base_response(task_id: str, *, task: str, dry_run: bool) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "task": task,
        "dry_run": dry_run,
        "status": "failed",
        "risk_level": classify_task_risk(task),
        "plan": [],
        "tool_results": [],
        "review": {},
        "estimated_cost_usd": 0.0,
        "final_answer": "",
        "error": None,
    }


def _persist_started(task_id: str, task: str, dry_run: bool) -> None:
    try:
        record_task_started(task_id, task, dry_run=dry_run)
    except Exception as exc:
        logger.warning("jarvis.mvp.persistence.start_failed task_id=%s err=%s", task_id, exc)


def _persist_completed(task_id: str, result: dict[str, Any]) -> None:
    try:
        record_task_completed(task_id, result)
    except Exception as exc:
        logger.warning("jarvis.mvp.persistence.complete_failed task_id=%s err=%s", task_id, exc)


def run_jarvis_task(task: str, *, dry_run: bool = True) -> dict[str, Any]:
    """Execute a Jarvis MVP task through the LangGraph pipeline."""
    task_id = str(uuid.uuid4())
    task_text = (task or "").strip()

    if not jarvis_enabled():
        out = _base_response(task_id, task=task_text, dry_run=dry_run)
        out.update(
            {
                "status": "failed",
                "final_answer": "Jarvis is disabled (JARVIS_ENABLED=false).",
            }
        )
        return out

    if jarvis_dry_run_only() and not dry_run:
        out = _base_response(task_id, task=task_text, dry_run=dry_run)
        out.update(
            {
                "status": "requires_approval",
                "final_answer": (
                    "Non-dry-run execution is blocked while JARVIS_DRY_RUN_ONLY=true. "
                    "Human approval is required."
                ),
                "review": {
                    "approved": False,
                    "flags": ["dry_run_only_blocked"],
                    "summary": "Execution blocked by dry-run-only policy.",
                },
            }
        )
        _persist_started(task_id, task_text, dry_run)
        _persist_completed(task_id, out)
        return out

    _persist_started(task_id, task_text, dry_run)

    initial_state: dict[str, Any] = {
        "task_id": task_id,
        "task": task_text,
        "dry_run": dry_run,
        "plan": [],
        "tool_results": [],
        "review": {},
        "estimated_cost_usd": 0.0,
        "final_answer": "",
        "model_calls": 0,
        "tool_calls": 0,
    }

    try:
        final_state = get_jarvis_graph().invoke(initial_state)
    except Exception as exc:
        logger.exception("jarvis.mvp.graph_failed task_id=%s err=%s", task_id, exc)
        out = _base_response(task_id, task=task_text, dry_run=dry_run)
        out.update(
            {
                "status": "failed",
                "final_answer": f"Jarvis task execution failed: {exc}",
                "error": str(exc),
            }
        )
        _persist_completed(task_id, out)
        return out

    status = str(final_state.get("status") or "")
    if not status:
        status = "requires_approval" if final_state.get("risk_level") == "high" else "completed"

    out = {
        "task_id": task_id,
        "status": status,
        "risk_level": str(final_state.get("risk_level") or classify_task_risk(task_text)),
        "plan": final_state.get("plan") or [],
        "tool_results": final_state.get("tool_results") or [],
        "review": final_state.get("review") or {},
        "estimated_cost_usd": float(final_state.get("estimated_cost_usd") or 0.0),
        "final_answer": str(final_state.get("final_answer") or ""),
    }
    _persist_completed(task_id, out)
    return out
