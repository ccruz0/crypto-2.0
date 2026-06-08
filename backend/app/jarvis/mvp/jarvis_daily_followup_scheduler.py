"""Daily follow-up detection and Telegram reminder (read-only, no execution)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_daily_followup_sync() -> dict:
    """
    Generate follow-ups and send Telegram summary if high/critical items exist.
    Safe to call from the trading scheduler loop.
    """
    try:
        from app.jarvis.mvp.followup_service import generate_followups

        result = generate_followups(send_telegram=True)
        logger.info(
            "daily_followup generated touched=%s telegram_sent=%s",
            result.get("followups_touched"),
            result.get("telegram_sent"),
        )
        return result
    except Exception as exc:
        logger.error("daily_followup failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
