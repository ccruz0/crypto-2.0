"""Utility functions for checking LIVE_TRADING status"""
import os
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_live_trading_status(db: Optional[Session] = None) -> bool:
    """
    Get LIVE_TRADING status.

    When a DB session is provided the database is the authoritative source and this
    **FAILS CLOSED**: if the setting cannot be read (DB error) or no row exists, the result
    is ``False`` (never live). This prevents a transient DB glitch from falling back to a
    stale ``LIVE_TRADING=true`` env var and placing real orders while the DB says OFF
    (live incident 2026-07-05: env was 'true' while DB was 'false', so a DB read error
    flipped the bot to live and it placed a real order).

    The environment-variable fallback applies ONLY when no DB session is available.

    Args:
        db: Optional database session. If provided, the DB is authoritative (fail-closed).

    Returns:
        bool: True only if live trading is explicitly enabled; False otherwise.
    """
    if db is not None:
        try:
            from app.models.trading_settings import TradingSettings
            setting = db.query(TradingSettings).filter(
                TradingSettings.setting_key == "LIVE_TRADING"
            ).first()

            if setting:
                enabled = setting.setting_value.lower() == "true"
                logger.debug(f"LIVE_TRADING from database: {enabled}")
                return enabled

            # No row yet: default OFF rather than trusting a possibly-stale env var.
            logger.debug("LIVE_TRADING setting not found in DB; defaulting to False (fail-closed)")
            return False
        except Exception as e:
            # FAIL CLOSED: a DB read error must NEVER enable live trading via the env fallback.
            logger.warning(f"Error reading LIVE_TRADING from database; failing CLOSED (False): {e}")
            return False

    # No DB session available: fall back to environment variable.
    env_value = os.getenv("LIVE_TRADING", "false").lower() == "true"
    logger.debug(f"LIVE_TRADING from environment (no DB session): {env_value}")
    return env_value

