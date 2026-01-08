"""Telegram health-check helper

Provides runtime verification of Telegram configuration and emits structured logs.
"""
import logging
import os
from typing import Dict, Any
from app.core.config import Settings

logger = logging.getLogger(__name__)


def check_telegram_health(origin: str = "startup") -> Dict[str, Any]:
    """
    Check Telegram config and emit structured logs.

    This function verifies:
    - RUN_TELEGRAM flag (enabled/disabled)
    - TELEGRAM_BOT_TOKEN presence
    - TELEGRAM_CHAT_ID presence
    - Source of configuration (env file or environment)

    Returns a dict with:
    - enabled: bool (whether Telegram should be enabled based on RUN_TELEGRAM)
    - token_present: bool (whether TELEGRAM_BOT_TOKEN is configured)
    - chat_id_present: bool (whether TELEGRAM_CHAT_ID is configured)
    - source: str (e.g. '.env.aws' / 'env')
    - origin: str (caller tag, e.g. 'startup', 'nightly_consistency')
    - fully_configured: bool (all required config is present)

    Args:
        origin: Tag identifying the caller (e.g. 'scheduler_startup', 'nightly_consistency', 'manual_check')

    Returns:
        Dict with health check results
    """
    settings = Settings()
    
    # Check RUN_TELEGRAM flag
    # Default to "false" (OFF) unless explicitly set to "true" or "1"
    # This ensures Telegram is OFF by default for safety
    run_telegram = (
        settings.RUN_TELEGRAM
        or os.getenv("RUN_TELEGRAM")
        or "false"  # Changed from "true" to "false" - Telegram OFF by default
    )
    run_telegram = run_telegram.strip().lower() if run_telegram else "false"
    enabled = run_telegram in ("1", "true", "yes", "on")
    
    # Check token and chat_id
    token = (settings.TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (settings.TELEGRAM_CHAT_ID or os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    
    token_present = bool(token)
    chat_id_present = bool(chat_id)
    
    # Guardrail: Even if RUN_TELEGRAM=1, require both token and chat_id
    # If either is missing, disable Telegram and log the reason
    if enabled and (not token_present or not chat_id_present):
        logger.warning(
            "[TELEGRAM_HEALTH] RUN_TELEGRAM=1 but secrets missing - disabling Telegram. "
            "token_present=%s chat_id_present=%s",
            token_present,
            chat_id_present
        )
        enabled = False
    
    # Determine source: if running in AWS and .env.aws is used, call it ".env.aws"
    # Otherwise "env" (could be .env, .env.local, or direct env vars)
    app_env = (os.getenv("APP_ENV") or settings.APP_ENV or "").strip().lower()
    environment = (os.getenv("ENVIRONMENT") or settings.ENVIRONMENT or "").strip().lower()
    
    if app_env == "aws" or environment == "aws":
        source = ".env.aws"
    else:
        source = "env"
    
    # Check if fully configured (all required pieces are present)
    fully_configured = enabled and token_present and chat_id_present
    
    # Emit structured log
    logger.info(
        "[TELEGRAM_HEALTH] origin=%s enabled=%s token_present=%s chat_id_present=%s source=%s fully_configured=%s",
        origin,
        enabled,
        token_present,
        chat_id_present,
        source,
        fully_configured,
    )
    
    # Emit warning if not fully configured
    if not fully_configured:
        missing = []
        if not enabled:
            missing.append("RUN_TELEGRAM not enabled")
        if not token_present:
            missing.append("TELEGRAM_BOT_TOKEN missing")
        if not chat_id_present:
            missing.append("TELEGRAM_CHAT_ID missing")
        
        logger.warning(
            "[TELEGRAM_HEALTH] origin=%s NOT_FULLY_CONFIGURED missing=%s",
            origin,
            ", ".join(missing),
        )
    
    return {
        "enabled": enabled,
        "token_present": token_present,
        "chat_id_present": chat_id_present,
        "source": source,
        "origin": origin,
        "fully_configured": fully_configured,
    }








