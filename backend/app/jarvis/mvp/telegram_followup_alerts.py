"""Read-only Telegram alerts for Jarvis follow-up reminders (no execution)."""

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


def format_followup_daily_alert(
    *,
    summary: dict[str, Any],
    followups: list[dict[str, Any]],
) -> str:
    """Format JARVIS FOLLOW-UP ALERT message."""
    severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    sorted_items = sorted(
        followups,
        key=lambda f: (
            severity_order.get(str(f.get("severity") or "medium"), 2),
            -int(f.get("reminder_count") or 0),
        ),
    )

    lines = [
        "JARVIS FOLLOW-UP ALERT",
        "",
        f"Critical: {summary.get('critical_followups', 0)}",
        f"High: {summary.get('high_followups', 0)}",
        f"Overdue: {summary.get('overdue_followups', 0)}",
        "",
        "Top follow-ups:",
    ]

    for idx, item in enumerate(sorted_items[:3], start=1):
        sev = str(item.get("severity") or "medium").upper()
        title = item.get("title") or "Untitled"
        lines.append(f"{idx}. [{sev}] {title}")

    lines.extend(["", "No actions executed."])
    return "\n".join(lines)


def send_followup_daily_alert(
    *,
    summary: dict[str, Any],
    followups: list[dict[str, Any]],
) -> bool:
    """Send daily follow-up summary when open high/critical items exist."""
    critical = int(summary.get("critical_followups") or 0)
    high = int(summary.get("high_followups") or 0)
    if critical == 0 and high == 0:
        return False

    chat_id = _chat_id()
    if not chat_id:
        logger.warning("followup alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_followup_daily_alert(summary=summary, followups=followups)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info(
            "followup daily alert sent=%s critical=%s high=%s",
            sent,
            critical,
            high,
        )
        return bool(sent)
    except Exception as exc:
        logger.warning("followup alert failed: %s", exc)
        return False
