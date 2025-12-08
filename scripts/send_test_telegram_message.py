#!/usr/bin/env python3
"""
Test script to verify the unified Telegram sending pipeline.

This script sends a test message through the same path used by:
- Daily sales report (working)
- Signal alerts
- Monitoring alerts
- All other alerts

Usage:
    Local: docker compose exec backend python scripts/send_test_telegram_message.py
    AWS:   docker compose --profile aws exec backend-aws python scripts/send_test_telegram_message.py
"""
import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import get_runtime_origin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def main():
    """Send a test Telegram message through the unified pipeline"""
    
    logger.info("=" * 80)
    logger.info("TELEGRAM PIPELINE TEST")
    logger.info("=" * 80)
    
    # Check runtime origin
    runtime_origin = get_runtime_origin()
    logger.info(f"Runtime Origin: {runtime_origin}")
    
    # Check Telegram configuration
    logger.info(f"Telegram Enabled: {telegram_notifier.enabled}")
    logger.info(f"Bot Token Present: {bool(telegram_notifier.bot_token)}")
    logger.info(f"Chat ID Present: {bool(telegram_notifier.chat_id)}")
    
    if not telegram_notifier.enabled:
        logger.error("❌ Telegram is disabled. Check RUN_TELEGRAM and env vars.")
        return 1
    
    # Build test message
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    test_message = f"""🧪 TEST ALERT FROM SHARED PIPELINE

This is a test message sent through the unified Telegram pipeline.

✅ Path: telegram_notifier.send_message()
✅ Origin: {runtime_origin}
✅ Timestamp: {timestamp}

If you receive this message, the unified pipeline is working correctly.
All alerts (signals, monitoring, watchlist, etc.) should use this same path.

🤖 Trading Bot Automático"""
    
    logger.info("Sending test message...")
    logger.info(f"Message preview: {test_message[:100]}...")
    
    # Send message through unified pipeline
    # This is the SAME path used by daily sales report
    success = telegram_notifier.send_message(test_message)
    
    if success:
        logger.info("=" * 80)
        logger.info("✅ SUCCESS: Test message sent successfully!")
        logger.info("=" * 80)
        logger.info("Check your Telegram chat to verify the message was received.")
        logger.info("This confirms the unified pipeline is working correctly.")
        return 0
    else:
        logger.error("=" * 80)
        logger.error("❌ FAILED: Test message was not sent")
        logger.error("=" * 80)
        logger.error("Check logs above for details:")
        logger.error("  - Look for [E2E_TEST_GATEKEEPER_BLOCK] if blocked")
        logger.error("  - Look for [TELEGRAM_ERROR] if API call failed")
        logger.error("  - Verify RUNTIME_ORIGIN=AWS in AWS environment")
        logger.error("  - Verify RUN_TELEGRAM=true")
        logger.error("  - Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set")
        return 1

if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
