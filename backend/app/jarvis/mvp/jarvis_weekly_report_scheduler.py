"""Weekly Chief of Staff executive report generation (read-only, no execution)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_weekly_executive_report_sync() -> dict:
    """
    Generate weekly executive priorities report if none exists in the last 6 days.
    Safe to call from the trading scheduler loop.
    """
    try:
        from app.jarvis.mvp.executive_report_service import create_executive_report

        result = create_executive_report(skip_if_recent=True, send_telegram=True)
        if result.get("skipped"):
            logger.info("weekly_executive_report skipped: %s", result.get("reason"))
        else:
            logger.info(
                "weekly_executive_report generated report_id=%s health=%s",
                result.get("report_id"),
                result.get("overall_health_score"),
            )
        return result
    except Exception as exc:
        logger.error("weekly_executive_report failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
