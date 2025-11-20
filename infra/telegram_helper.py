"""
Telegram Helper for Infrastructure Monitoring
Reuses the same Telegram configuration as the main application
"""
import os
import logging
import requests
from typing import Optional

logger = logging.getLogger(__name__)


def send_telegram_message(text: str) -> bool:
    """
    Send a message to Telegram using the same bot token and chat ID as the main app.
    
    Args:
        text: Message text to send (supports HTML formatting)
    
    Returns:
        True if message was sent successfully, False otherwise
    """
    bot_token = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.getenv("TELEGRAM_CHAT_ID") or "").strip()
    
    if not bot_token or not chat_id:
        logger.warning("Telegram disabled: missing env vars")
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
        
        logger.info("Telegram message sent successfully")
        return True
        
    except Exception as e:
        logger.error(f"Failed to send Telegram message: {e}")
        return False

