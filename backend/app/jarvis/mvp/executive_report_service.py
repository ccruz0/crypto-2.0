"""Orchestrate Chief of Staff report generation, persistence, and alerts."""

from __future__ import annotations

import logging

from app.jarvis.mvp.chief_of_staff import generate_executive_report
from app.jarvis.mvp.executive_report_persistence import (
    get_executive_report,
    record_executive_report,
    report_generated_within_days,
)
from app.jarvis.mvp.telegram_executive_report_alerts import send_weekly_executive_report_alert

logger = logging.getLogger(__name__)


def create_executive_report(*, skip_if_recent: bool = False, send_telegram: bool = True) -> dict:
    """
    Generate, persist, and optionally alert on a new executive priorities report.
    Does not execute any remediation.
    """
    if skip_if_recent and report_generated_within_days(days=6):
        logger.info("executive_report skipped: report generated within last 6 days")
        from app.jarvis.mvp.executive_report_persistence import get_latest_executive_report

        latest = get_latest_executive_report()
        if latest:
            return {**latest, "skipped": True, "reason": "recent_report_exists"}
        return {"skipped": True, "reason": "recent_report_exists"}

    report = generate_executive_report()
    record_executive_report(report=report)

    if send_telegram:
        send_weekly_executive_report_alert(report)

    stored = get_executive_report(report["report_id"])
    if stored is None:
        raise RuntimeError("Executive report persistence failed")

    logger.info(
        "executive_report created report_id=%s health_score=%s priorities=%d",
        stored["report_id"],
        stored.get("overall_health_score"),
        len(stored.get("top_priorities") or []),
    )
    return stored
