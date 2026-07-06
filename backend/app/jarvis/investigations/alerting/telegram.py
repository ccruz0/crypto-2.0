"""Read-only Telegram alerts for Jarvis investigation findings (no execution)."""

from __future__ import annotations

import logging
import os
from typing import Any

from app.jarvis.investigations.alerting.types import AlertRecord, AlertSeverity

logger = logging.getLogger(__name__)


def _chat_id() -> str:
    return (
        os.environ.get("JARVIS_TELEGRAM_CHAT_ID")
        or os.environ.get("TELEGRAM_CHAT_ID")
        or ""
    ).strip()


def format_investigation_alert_message(
    alert: AlertRecord,
    *,
    investigation_type: str = "",
) -> str:
    """Format Telegram message for an investigation alert."""
    inv_type = investigation_type or alert.source or "investigation"
    timestamp = alert.last_seen or alert.created_at or ""
    evidence_count = len(alert.evidence or [])
    lines = [
        "JARVIS INVESTIGATION ALERT",
        "",
        f"Severity: {alert.severity}",
        f"Type: {inv_type}",
        f"Time: {timestamp}",
        f"Summary: {alert.summary[:800]}",
        f"Evidence: {evidence_count}",
        f"Investigation: {alert.investigation_id or 'n/a'}",
    ]
    if alert.deduplicated and alert.occurrence_count > 1:
        lines.append(f"Occurrences: {alert.occurrence_count}")
    lines.extend(["", "Read-only alert — no actions executed."])
    return "\n".join(lines)


def should_send_telegram(alert: AlertRecord, *, info_enabled: bool) -> bool:
    # Only send Telegram alerts for CRITICAL issues. WARNING and INFO are logged but not notified
    # (read-only warnings shouldn't interrupt the operator; log them instead)
    if alert.severity == AlertSeverity.CRITICAL.value:
        return True
    if alert.severity == AlertSeverity.INFO.value:
        return info_enabled
    return False


def send_investigation_alert(
    alert: AlertRecord,
    *,
    investigation_type: str = "",
    info_enabled: bool = False,
) -> bool:
    """Send alert via existing Jarvis Telegram infrastructure."""
    if not should_send_telegram(alert, info_enabled=info_enabled):
        return False

    chat_id = _chat_id()
    if not chat_id:
        logger.warning("investigation alert skipped: no TELEGRAM_CHAT_ID configured")
        return False

    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_investigation_alert_message(alert, investigation_type=investigation_type)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info(
            "investigation alert telegram sent=%s severity=%s alert_id=%s",
            sent,
            alert.severity,
            alert.alert_id,
        )
        return bool(sent)
    except Exception as exc:
        logger.warning("investigation alert telegram failed: %s", exc)
        return False


def format_daily_health_report_message(report: dict[str, Any]) -> str:
    """Format daily health summary for Telegram."""
    lines = [
        "JARVIS DAILY HEALTH SUMMARY",
        "",
        f"Date: {report.get('report_date', '')}",
        f"Investigations: {report.get('investigations_executed', 0)}",
        f"Success rate: {report.get('success_rate_pct', 0)}%",
        f"Failures: {report.get('failures', 0)}",
        f"Warnings: {report.get('warnings', 0)}",
        f"Critical alerts: {report.get('critical_alerts', 0)}",
        f"Avg runtime: {report.get('average_runtime_ms', 0)}ms",
        "",
        "Top recurring issues:",
    ]
    for idx, issue in enumerate(report.get("top_recurring_issues") or [], start=1):
        title = issue.get("title") or issue.get("alert_type") or "Unknown"
        count = issue.get("occurrence_count") or issue.get("count") or 0
        lines.append(f"{idx}. {title} ({count}x)")
    if len(lines) == 12:
        lines.append("(none)")
    lines.extend(["", "Read-only summary — no actions executed."])
    return "\n".join(lines)


def send_daily_health_report(report: dict[str, Any]) -> bool:
    chat_id = _chat_id()
    if not chat_id:
        logger.warning("daily health report skipped: no TELEGRAM_CHAT_ID configured")
        return False
    try:
        from app.jarvis.telegram_service import TelegramMissionService

        message = format_daily_health_report_message(report)
        sent = TelegramMissionService().send_message(chat_id, message)
        logger.info("daily health report telegram sent=%s date=%s", sent, report.get("report_date"))
        return bool(sent)
    except Exception as exc:
        logger.warning("daily health report telegram failed: %s", exc)
        return False
