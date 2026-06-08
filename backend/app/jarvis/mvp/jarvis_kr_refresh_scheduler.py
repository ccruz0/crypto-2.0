"""Daily KR metric refresh scheduler wrapper (read-only, no execution)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def run_kr_refresh_sync() -> dict:
    """
    Refresh key result metrics from read-only sources and send alerts if needed.
    Safe to call from the trading scheduler loop.
    """
    try:
        from app.jarvis.mvp.kr_refresh_service import refresh_key_results

        result = refresh_key_results(send_telegram=True)
        logger.info(
            "daily_kr_refresh updated=%s failed=%s telegram_sent=%s",
            result.get("updated_count"),
            result.get("failed_count"),
            result.get("telegram_sent"),
        )
        return result
    except Exception as exc:
        logger.error("daily_kr_refresh failed: %s", exc, exc_info=True)
        return {"error": str(exc)}
