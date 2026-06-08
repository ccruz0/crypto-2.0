"""Read-only Telegram alerts for Jarvis weekly executive reports (no execution)."""

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


def format_weekly_executive_report_alert(report: dict[str, Any]) -> str:
    """Format JARVIS WEEKLY REPORT message."""
    health = int(report.get("overall_health_score") or 0)
    priorities = report.get("top_priorities") or []
    total_savings = float(report.get("total_potential_savings_usd") or 0)

    if not total_savings:
        for item in priorities:
            total_savings += float(item.get("estimated_savings_usd") or 0)

    lines = [
        "JARVIS WEEKLY REPORT",
        "",
        f"Health Score: {health}",
        "",
        "Top Priorities:",
    ]

    for item in priorities[:3]:
        rank = item.get("priority", "?")
        title = item.get("title", "Untitled")
        lines.append(f"{rank}. {title}")

    lines.extend(
        [
            "",
            "Potential savings:",
            f"${total_savings:,.2f}/month",
        ]
    )

    lessons = report.get("lessons_learned") or []
    if lessons:
        lines.extend(["", "Lessons Learned:"])
        for lesson in lessons[:3]:
            lines.append(f"- {lesson}")

    execution = report.get("execution_review") or {}
    if execution:
        lines.extend(
            [
                "",
                "Execution Review:",
                f"Active: {execution.get('active', 0)}",
                f"Blocked: {execution.get('blocked', 0)}",
                f"Overdue: {execution.get('overdue', 0)}",
            ]
        )
        top_risk = execution.get("top_risk")
        if top_risk:
            lines.extend(["", f"Top Risk: {top_risk}"])

    lines.extend(["", "No actions executed."])
    return "\n".join(lines)


def send_weekly_executive_report_alert(report: dict[str, Any]) -> bool:
    """Send weekly executive summary to Telegram."""
    chat_id = _chat_id()
    if not chat_id:
        logger.warning("executive_report alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_weekly_executive_report_alert(report)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info("executive_report weekly alert sent=%s report_id=%s", sent, report.get("report_id"))
        return bool(sent)
    except Exception as exc:
        logger.warning("executive_report alert failed: %s", exc)
        return False
