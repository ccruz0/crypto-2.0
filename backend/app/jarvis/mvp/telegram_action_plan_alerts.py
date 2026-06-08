"""Read-only Telegram alerts for critical Jarvis Action Plans (no execution)."""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)


def _chat_id() -> str:
    return (
        os.environ.get("JARVIS_TELEGRAM_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    ).strip()


def format_action_plan_alert(plan: dict[str, Any]) -> str:
    """Format ACTION PLAN GENERATED message for critical severity plans."""
    finding = plan.get("finding_summary") or "Critical audit finding requires review"
    savings = float(plan.get("estimated_savings_usd") or 0)
    severity = str(plan.get("severity") or "critical").upper()

    return (
        "ACTION PLAN GENERATED\n\n"
        f"Severity: {severity}\n"
        f"Estimated savings: ${savings:,.2f}/mo\n"
        f"Finding: {finding}\n\n"
        "Review required.\n\n"
        "No execution performed."
    )


def send_action_plan_alert(plan: dict[str, Any]) -> bool:
    """Send Telegram alert only when plan severity is critical."""
    severity = str(plan.get("severity") or "").lower()
    if severity != "critical":
        logger.info("action_plan alert skipped: severity=%s (not critical)", severity)
        return False

    chat_id = _chat_id()
    if not chat_id:
        logger.warning("action_plan alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_action_plan_alert(plan)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info("action_plan critical alert sent=%s plan_id=%s", sent, plan.get("plan_id"))
        return bool(sent)
    except Exception as exc:
        logger.warning("action_plan alert failed: %s", exc)
        return False
