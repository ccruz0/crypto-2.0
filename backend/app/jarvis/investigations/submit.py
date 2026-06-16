"""Shared read-only investigation submission (human-equivalent path)."""

from __future__ import annotations

from typing import Any

from app.jarvis.execution.safety import SafetyLevel, classify_text
from app.jarvis.investigations.investigation_report import InvestigationReport
from app.jarvis.investigations.investigation_runner import run_investigation
from app.jarvis.mvp.config import jarvis_enabled


class InvestigationBlockedError(Exception):
    """Raised when safety policy blocks an investigation objective."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def submit_investigation_readonly(
    objective: str,
    *,
    investigation_id: str | None = None,
    persist: bool = True,
    attachments: list[dict[str, Any]] | None = None,
) -> InvestigationReport:
    """
    Submit an investigation exactly as the Phase 4A API would — same gates, no privileges.

    Read-only: investigations only; no patches, trades, GitHub writes, or code execution.
    """
    if not jarvis_enabled():
        raise InvestigationBlockedError("Jarvis is disabled (JARVIS_ENABLED=false)")
    objective_text = (objective or "").strip()
    if not objective_text:
        raise ValueError("investigation objective is required")
    if classify_text(objective_text) == SafetyLevel.FORBIDDEN:
        raise InvestigationBlockedError(
            "Objective blocked by safety policy (forbidden action or trading intent)"
        )
    return run_investigation(
        objective_text,
        investigation_id=investigation_id,
        persist=persist,
        attachments=attachments,
    )
