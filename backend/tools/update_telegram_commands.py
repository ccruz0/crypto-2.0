#!/usr/bin/env python3
"""
Update Telegram bot commands to only show /menu
"""
import sys
sys.path.insert(0, '/app')

import os
import requests
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Get bot token from environment
BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or "").strip()

def update_bot_commands():
    """Update bot commands to only show /menu"""
    if not BOT_TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN missing. Cannot update commands.")
        return False
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setMyCommands"
        # Only keep essential command - remove most to keep menu clean
        commands = [
            {"command": "menu", "description": "Abrir menú principal"},
        ]
        
        payload = {
            "commands": commands
        }
        
        logger.info(f"Updating bot commands to only show /menu...")
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        
        result = response.json()
        if result.get("ok"):
            logger.info("✅ Bot commands updated successfully! Only /menu will be shown.")
            return True
        else:
            logger.error(f"❌ Failed to update commands: {result}")
            return False
            
    except Exception as e:
        logger.error(f"❌ Error updating bot commands: {e}", exc_info=True)
        return False

if __name__ == '__main__':
    success = update_bot_commands()
    sys.exit(0 if success else 1)

