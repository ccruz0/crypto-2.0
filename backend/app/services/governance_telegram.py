"""
Concise Telegram summaries for governance lifecycle (not every event).

Uses Claw channel (same as agent approvals) when configured.
"""

from __future__ import annotations

import logging
import os
from typing import Sequence

logger = logging.getLogger(__name__)

# Major transitions only
_KINDS = frozenset({"awaiting_approval", "approved", "denied", "completed", "failed"})


def send_governance_telegram_summary(
    kind: str,
    *,
    task_id: str,
    lines: Sequence[str],
    manifest_id: str | None = None,
) -> bool:
    if kind not in _KINDS:
        return False
    if (os.environ.get("RUN_TELEGRAM") or "").strip().lower() in ("0", "false", "no", "off"):
        return False

    header = "🔐 GOVERNANCE"
    if kind == "awaiting_approval":
        header = "🔐 GOVERNANCE — approval needed"
    elif kind == "approved":
        header = "✅ GOVERNANCE — approved"
    elif kind == "denied":
        header = "⛔ GOVERNANCE — denied"
    elif kind == "completed":
        header = "✅ GOVERNANCE — completed"
    elif kind == "failed":
        header = "❌ GOVERNANCE — failed"

    body_lines = [f"<b>Task</b> <code>{task_id}</code>"] + list(lines)
    try:
        from app.services.governance_refs import append_governance_telegram_trace

        append_governance_telegram_trace(body_lines, governance_task_id=task_id, manifest_id=manifest_id)
    except Exception:
        pass
    body = "\n".join(body_lines)
    text = f"{header}\n\n{body}"[:3900]

    try:
        from app.services.claw_telegram import send_claw_message
        sent, _ = send_claw_message(
            text,
            message_type="GOVERNANCE",
            source_module="governance_telegram",
        )
        return bool(sent)
    except Exception as e:
        logger.warning("governance telegram send failed: %s", e)
        return False
