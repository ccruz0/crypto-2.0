"""Typed structures for the Jarvis agent HTTP/API layer.

Runtime validation of planner output uses :class:`app.jarvis.plan_validation.PlanValidated`
(Pydantic). ``PlanDict`` remains the loose response shape for ``input`` / ``plan`` / ``result``.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict


class PlanDict(TypedDict, total=False):
    """Structured plan exposed to clients (matches validated fields when successful)."""

    action: str
    args: dict[str, Any]
    reasoning: str


class JarvisRunResult(TypedDict, total=False):
    """Response from :func:`orchestrator.run_jarvis`."""

    input: str
    plan: PlanDict
    result: Any
    jarvis_run_id: str
    error: NotRequired[str]
