"""Async loop for daily health report generation."""

from __future__ import annotations

import asyncio
import logging

from app.jarvis.investigations.alerting import config as alert_config
from app.jarvis.investigations.alerting.daily_report import maybe_generate_daily_report

logger = logging.getLogger(__name__)

_loop_running = False
_last_report_at: str = ""
_last_report_result: dict = {}


def get_daily_report_runtime_state() -> dict:
    return {
        "daily_report_loop_running": _loop_running,
        "last_report_at": _last_report_at,
        "last_report_result": dict(_last_report_result),
    }


async def start_daily_report_loop() -> None:
    """Check hourly whether the daily health report should be generated."""
    global _loop_running, _last_report_at, _last_report_result

    _loop_running = True
    logger.info(
        "daily_report_loop_started hour_utc=%d",
        alert_config.jarvis_daily_report_hour_utc(),
    )

    loop = asyncio.get_running_loop()
    while True:
        if not alert_config.jarvis_daily_report_enabled():
            await asyncio.sleep(300)
            continue
        try:
            result = await loop.run_in_executor(None, maybe_generate_daily_report)
            if result:
                from datetime import datetime, timezone

                _last_report_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                _last_report_result = result
                logger.info(
                    "daily_report_generated report_id=%s telegram_sent=%s",
                    result.get("report_id"),
                    result.get("telegram_sent"),
                )
        except Exception as exc:
            logger.exception("daily_report_loop_error: %s", exc)
        await asyncio.sleep(300)
