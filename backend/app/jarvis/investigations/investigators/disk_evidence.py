"""Schemas for HostDiskFillingUp disk-pressure evidence and recommendation.

The recommendation carries TEXT ONLY (``suggested_action`` is a string). There
is deliberately no executable/callable field and no link from this model to any
action so it cannot drive a write/execute path.
"""

from __future__ import annotations

from datetime import datetime, timezone

from pydantic import BaseModel, Field


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CommandResult(BaseModel):
    """Result of one read-only, allowlisted command run via atp_ssm_runner."""

    command: str
    ok: bool = False
    stdout: str = ""
    stderr: str = ""
    status: str = ""
    error: str | None = None


class DiskEvidence(BaseModel):
    """Collected read-only evidence for the HostDiskFillingUp alert."""

    alert: str = "HostDiskFillingUp"
    gathered_at: str = Field(default_factory=_utcnow_iso)
    commands: list[CommandResult] = Field(default_factory=list)

    def combined_stdout(self) -> str:
        chunks: list[str] = []
        for c in self.commands:
            body = c.stdout if c.ok else (c.error or c.stderr or "(no output)")
            chunks.append(f"$ {c.command}\n{body}")
        return "\n\n".join(chunks)


class DiskRecommendation(BaseModel):
    """Advisory, text-only output. NOT an action and not wired to one."""

    alert: str
    summary: str
    suggested_action: str
    evidence: DiskEvidence
    model_id: str | None = None
    generated_by: str = "jarvis.investigations.investigators.disk_pressure"
