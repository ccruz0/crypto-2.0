"""Phase 5 audit logging helpers (never log secrets)."""

from __future__ import annotations

import re
from typing import Any

from app.jarvis.execution.audit import log_execution_event

_SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|secret|token|password|credential)\s*[:=]\s*\S+"),
    re.compile(r"(?i)Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"(?i)JARVIS_[A-Z_]+=\S+"),
)


def _sanitize(text: str) -> str:
    out = text or ""
    for pattern in _SECRET_PATTERNS:
        out = pattern.sub("[REDACTED]", out)
    return out[:2000]


def _sanitize_metadata(meta: dict[str, Any]) -> dict[str, Any]:
    clean: dict[str, Any] = {}
    for key, value in meta.items():
        if isinstance(value, str):
            clean[key] = _sanitize(value)
        elif isinstance(value, list):
            clean[key] = [_sanitize(str(v)) if isinstance(v, str) else v for v in value]
        else:
            clean[key] = value
    return clean


def log_phase5_event(
    *,
    task_id: str,
    actor: str,
    approval_gate: str,
    action: str,
    branch_name: str = "",
    changed_files: list[str] | None = None,
    test_command: str = "",
    test_result: str = "",
    pr_url: str = "",
    duration_ms: int = 0,
    extra: dict[str, Any] | None = None,
) -> str:
    """Log a Phase 5 audit event with structured metadata."""
    metadata = _sanitize_metadata(
        {
            "phase": "5",
            "approval_gate": approval_gate,
            "action": action,
            "branch_name": branch_name,
            "changed_files": changed_files or [],
            "test_command": test_command,
            "test_result": test_result,
            "pr_url": pr_url,
            **(extra or {}),
        }
    )
    summary_parts = [f"gate={approval_gate}", f"action={action}"]
    if branch_name:
        summary_parts.append(f"branch={branch_name}")
    if test_result:
        summary_parts.append(f"tests={test_result}")
    if pr_url:
        summary_parts.append(f"pr={pr_url}")

    return log_execution_event(
        task_id=task_id,
        agent="change_execution",
        tool=action,
        input_summary=_sanitize(f"actor={actor} gate={approval_gate}"),
        output_summary=_sanitize(" ".join(summary_parts)),
        duration_ms=duration_ms,
        metadata=metadata,
    )
