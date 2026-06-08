"""Read-only Telegram alerts for Jarvis KR metric refresh (no execution)."""

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


def format_kr_alert(
    *,
    objective_title: str,
    kr_title: str,
    current_value: float | str,
    target_value: float | str,
    status: str,
    unit: str | None = None,
    reason: str | None = None,
) -> str:
    """Format JARVIS KR ALERT message."""
    unit_suffix = f" {unit}" if unit else ""
    lines = [
        "JARVIS KR ALERT",
        "",
        f"Objective: {objective_title}",
        f"Key Result: {kr_title}",
        f"Current: {current_value}{unit_suffix}",
        f"Target: {target_value}{unit_suffix}",
        f"Status: {status}",
    ]
    if reason:
        lines.append(f"Reason: {reason}")
    lines.extend(["", "No action executed."])
    return "\n".join(lines)


def send_kr_alert(
    *,
    objective_title: str,
    kr_title: str,
    current_value: float | str,
    target_value: float | str,
    status: str,
    unit: str | None = None,
    reason: str | None = None,
) -> bool:
    """Send a single KR alert to Telegram."""
    chat_id = _chat_id()
    if not chat_id:
        logger.warning("kr alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_kr_alert(
            objective_title=objective_title,
            kr_title=kr_title,
            current_value=current_value,
            target_value=target_value,
            status=status,
            unit=unit,
            reason=reason,
        )
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info("kr alert sent=%s objective=%s kr=%s", sent, objective_title, kr_title)
        return bool(sent)
    except Exception as exc:
        logger.warning("kr alert failed: %s", exc)
        return False


def send_kr_refresh_alerts(alerts: list[dict[str, Any]]) -> int:
    """Send all queued KR refresh alerts. Returns count sent."""
    sent = 0
    for alert in alerts:
        if send_kr_alert(
            objective_title=str(alert.get("objective_title") or "Unknown"),
            kr_title=str(alert.get("kr_title") or "Unknown"),
            current_value=alert.get("current_value", "—"),
            target_value=alert.get("target_value", "—"),
            status=str(alert.get("status") or "unknown"),
            unit=alert.get("unit"),
            reason=alert.get("reason"),
        ):
            sent += 1
    return sent
