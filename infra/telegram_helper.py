"""
Telegram Helper for Infrastructure Monitoring

Routes to AWS Alerts (@AWS_alerts_hilovivo_bot) for EC2/Docker/health.
Uses TELEGRAM_ALERT_BOT_TOKEN + TELEGRAM_ALERT_CHAT_ID (Alertmanager config),
fallback to TELEGRAM_AWS_ALERTS_* or TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_OPS.
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


def send_telegram_message(text: str) -> bool:
    """
    Send infra/health message to AWS Alerts channel.

    Prefer: TELEGRAM_ALERT_* (Alertmanager) or TELEGRAM_AWS_ALERTS_*
    Fallback: TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_OPS (ops channel)
    """
    bot_token = (
        (os.getenv("TELEGRAM_ALERT_BOT_TOKEN") or os.getenv("TELEGRAM_AWS_ALERTS_BOT_TOKEN") or "").strip()
    )
    chat_id = (
        (os.getenv("TELEGRAM_ALERT_CHAT_ID") or os.getenv("TELEGRAM_AWS_ALERTS_CHAT_ID") or "").strip()
    )
    if not bot_token or not chat_id:
        bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
        chat_id = (os.getenv("TELEGRAM_CHAT_ID_OPS") or os.getenv("TELEGRAM_CHAT_ID") or "").strip()

    if not bot_token or not chat_id:
        logger.warning(
            "[TELEGRAM_ROUTE] category=INFRA destination=AWS_ALERTS missing_config=True "
            "hint=set TELEGRAM_ALERT_BOT_TOKEN and TELEGRAM_ALERT_CHAT_ID for infra alerts"
        )
        return False
    
    try:
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML"
        }
        
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()

        logger.info(
            "[TELEGRAM_ROUTE] category=INFRA destination=AWS_ALERTS source=infra/telegram_helper sent=True"
        )
        return True
        
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False

