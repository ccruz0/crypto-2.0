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
    """Send daily follow-up summary when actionable high/critical/overdue items exist."""
    if not should_send_followup_daily_alert(summary=summary, followups=followups):
        logger.info(
            "followup daily alert skipped (quiet): critical=%s high=%s overdue=%s open=%s",
            summary.get("critical_followups"),
            summary.get("high_followups"),
            summary.get("overdue_followups"),
            len(followups),
        )
        return False

    critical = int(summary.get("critical_followups") or 0)
    high = int(summary.get("high_followups") or 0)
    overdue = int(summary.get("overdue_followups") or 0)

    chat_id = _chat_id()
    if not chat_id:
        logger.warning("followup alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_followup_daily_alert(summary=summary, followups=followups)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info(
            "followup daily alert sent=%s critical=%s high=%s overdue=%s",
            sent,
            critical,
            high,
            overdue,
        )
        return bool(sent)
    except Exception as exc:
        logger.warning("followup alert failed: %s", exc)
        return False


def should_send_followup_daily_alert(
    *,
    summary: dict[str, Any],
    followups: list[dict[str, Any]] | None = None,
) -> bool:
    """Send only when overdue, critical, or unique high-severity open items exist."""
    overdue = int(summary.get("overdue_followups") or 0)
    critical = int(summary.get("critical_followups") or 0)
    if overdue > 0 or critical > 0:
        return True

    high = int(summary.get("high_followups") or 0)
    if high <= 0:
        return False

    items = followups or []
    if not items:
        return True

    unique_high = {
        (str(f.get("source_type") or ""), str(f.get("source_id") or ""))
        for f in items
        if str(f.get("status") or "open") == "open"
        and str(f.get("severity") or "").lower() == "high"
    }
    return len(unique_high) > 0
