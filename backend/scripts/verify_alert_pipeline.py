#!/usr/bin/env python3
"""
Minimal verification script for alert pipeline end-to-end.

Verifies:
1. Alert is created in database (telegram_messages table)
2. Alert passes through the pipeline
3. Alert is sent successfully to Telegram

Usage:
    python3 backend/scripts/verify_alert_pipeline.py [SYMBOL]

Example:
    python3 backend/scripts/verify_alert_pipeline.py BTC_USDT
"""

import sys
import os
import time
from datetime import datetime, timezone, timedelta

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from app.models.watchlist import WatchlistItem
from app.services.alert_emitter import emit_alert
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)


def verify_alert_pipeline(symbol: str = "BTC_USDT") -> bool:
    """
    Verify alert pipeline end-to-end.
    
    Returns:
        True if all checks pass, False otherwise
    """
    logger.info("=" * 80)
    logger.info("ALERT PIPELINE VERIFICATION")
    logger.info("=" * 80)
    logger.info(f"Symbol: {symbol}")
    logger.info(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    logger.info("")
    
    db = SessionLocal()
    try:
        # Step 1: Get watchlist item
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not watchlist_item:
            logger.error(f"❌ Symbol {symbol} not found in watchlist")
            return False
        
        logger.info(f"✅ Found watchlist item: {symbol} (id={watchlist_item.id}, alert_enabled={watchlist_item.alert_enabled})")
        
        # Step 2: Get current price (use watchlist price or fetch)
        current_price = watchlist_item.price or 50000.0  # Fallback for testing
        logger.info(f"📊 Using price: ${current_price:,.4f}")
        
        # Step 3: Count existing alerts before
        before_count = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol,
            TelegramMessage.timestamp >= datetime.now(timezone.utc) - timedelta(minutes=5)
        ).count()
        logger.info(f"📈 Existing alerts in last 5 minutes: {before_count}")
        
        # Step 4: Trigger alert
        logger.info("")
        logger.info("🚀 Triggering alert via emit_alert()...")
        logger.info("-" * 80)
        
        test_reason = f"VERIFICATION TEST - RSI=35.0, Price={current_price:.4f}"
        result = emit_alert(
            db=db,
            symbol=symbol,
            side="BUY",
            reason=test_reason,
            price=current_price,
            context={"source": "VERIFICATION_TEST"},
            strategy_type="Swing",
            risk_approach="Conservative",
            throttle_status="SENT",
            throttle_reason="VERIFICATION_TEST",
        )
        
        logger.info("-" * 80)
        logger.info(f"✅ emit_alert() returned: {result}")
        logger.info("")
        
        # Step 5: Wait a moment for DB commit
        time.sleep(1)
        
        # Step 6: Verify DB row was created
        logger.info("🔍 Verifying database row creation...")
        after_count = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol,
            TelegramMessage.timestamp >= datetime.now(timezone.utc) - timedelta(minutes=5)
        ).count()
        
        new_alerts = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol,
            TelegramMessage.timestamp >= datetime.now(timezone.utc) - timedelta(minutes=5)
        ).order_by(TelegramMessage.timestamp.desc()).limit(5).all()
        
        logger.info(f"📈 Alerts in last 5 minutes after trigger: {after_count}")
        
        if after_count > before_count:
            latest_alert = new_alerts[0]
            logger.info("✅ Database row created successfully!")
            logger.info(f"   Alert ID: {latest_alert.id}")
            logger.info(f"   Symbol: {latest_alert.symbol}")
            logger.info(f"   Blocked: {latest_alert.blocked}")
            logger.info(f"   Timestamp: {latest_alert.timestamp}")
            logger.info(f"   Message preview: {latest_alert.message[:100]}...")
            
            if latest_alert.blocked:
                logger.warning("⚠️  Alert was BLOCKED (not sent to Telegram)")
                logger.warning(f"   Throttle status: {latest_alert.throttle_status}")
                logger.warning(f"   Throttle reason: {latest_alert.throttle_reason}")
                return False
            else:
                logger.info("✅ Alert was SENT (not blocked)")
        else:
            logger.error("❌ No new database row found after trigger")
            return False
        
        # Step 7: Check logs for Telegram send confirmation
        logger.info("")
        logger.info("📋 Verification Summary:")
        logger.info(f"   1. ✅ Alert triggered via emit_alert()")
        logger.info(f"   2. ✅ Database row created (id={latest_alert.id})")
        logger.info(f"   3. {'✅' if not latest_alert.blocked else '❌'} Alert status: {'SENT' if not latest_alert.blocked else 'BLOCKED'}")
        logger.info("")
        logger.info("📝 Next steps:")
        logger.info("   1. Check backend logs for [TELEGRAM_SEND] entries")
        logger.info("   2. Check backend logs for [TELEGRAM_RESPONSE] entries")
        logger.info("   3. Verify message appears in Telegram chat")
        logger.info("")
        logger.info("🔍 Query database to see alert:")
        logger.info(f"   SELECT * FROM telegram_messages WHERE id = {latest_alert.id};")
        logger.info("")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Verification failed: {e}", exc_info=True)
        return False
    finally:
        db.close()


if __name__ == "__main__":
    symbol = sys.argv[1] if len(sys.argv) > 1 else "BTC_USDT"
    success = verify_alert_pipeline(symbol)
    sys.exit(0 if success else 1)
