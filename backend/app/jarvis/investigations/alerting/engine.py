"""Central alert engine for investigation findings."""

from __future__ import annotations

import logging
from typing import Any

from app.jarvis.investigations.alerting import config as alert_config
from app.jarvis.investigations.alerting.fingerprint import build_fingerprint
from app.jarvis.investigations.alerting.persistence import upsert_alert
from app.jarvis.investigations.alerting.severity import classify_investigation_report, classify_task_failure
from app.jarvis.investigations.alerting.telegram import send_investigation_alert
from app.jarvis.investigations.alerting.types import AlertInput, AlertRecord

logger = logging.getLogger(__name__)


def _emit_alert(alert_input: AlertInput, *, investigation_type: str = "") -> AlertRecord | None:
    if not alert_config.jarvis_alerting_enabled():
        return None

    fingerprint = build_fingerprint(alert_input)
    try:
        record = upsert_alert(
            alert_input,
            fingerprint=fingerprint,
            suppression_window_hours=alert_config.jarvis_alert_suppression_window_hours(),
        )
    except Exception as exc:
        logger.warning("alert engine persistence failed: %s", exc)
        return None

    record.telegram_sent = send_investigation_alert(
        record,
        investigation_type=investigation_type or alert_input.source,
        info_enabled=alert_config.jarvis_alert_info_telegram_enabled(),
    )
    return record


def process_investigation_alert(
    report: Any,
    *,
    source: str,
    investigation_type: str = "",
) -> AlertRecord | None:
    """
    Process a completed investigation report into an alert.

    Read-only: stores alert, optionally sends Telegram. Never modifies production state.
    """
    if not alert_config.jarvis_alerting_enabled():
        return None

    alert_input = classify_investigation_report(report, source=source)
    if alert_input is None:
        return None

    return _emit_alert(alert_input, investigation_type=investigation_type or source)


def process_task_failure_alert(
    *,
    source: str,
    objective: str,
    error_message: str,
    investigation_id: str | None = None,
    investigation_type: str = "",
) -> AlertRecord | None:
    """Emit a CRITICAL alert when a scheduled investigation task fails."""
    if not alert_config.jarvis_alerting_enabled():
        return None

    alert_input = classify_task_failure(
        source=source,
        objective=objective,
        error_message=error_message,
        investigation_id=investigation_id,
    )
    return _emit_alert(alert_input, investigation_type=investigation_type or source)
