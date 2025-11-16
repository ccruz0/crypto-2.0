"""Utility functions for checking LIVE_TRADING status"""
import os
import logging
from typing import Optional
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def get_live_trading_status(db: Optional[Session] = None) -> bool:
    """
    Get LIVE_TRADING status from database first, then fallback to environment variable.
    
    Args:
        db: Optional database session. If provided, checks database first.
    
    Returns:
        bool: True if LIVE_TRADING is enabled, False otherwise
    """
    # Try database first if session is available
    if db:
        try:
            from app.models.trading_settings import TradingSettings
            setting = db.query(TradingSettings).filter(
                TradingSettings.setting_key == "LIVE_TRADING"
            ).first()
            
            if setting:
                enabled = setting.setting_value.lower() == "true"
                logger.debug(f"LIVE_TRADING from database: {enabled}")
                return enabled
        except Exception as e:
            logger.warning(f"Error reading LIVE_TRADING from database: {e}")
    
    # Fallback to environment variable
    env_value = os.getenv("LIVE_TRADING", "false").lower() == "true"
    logger.debug(f"LIVE_TRADING from environment: {env_value}")
    return env_value

