#!/usr/bin/env python3
"""
Script de fallback para habilitar alertas directamente en la base de datos.
Ejecutar en el servidor con: python3 fix_alerts_fallback.py
"""

import sys
import os

# Add backend to path
sys.path.insert(0, "/app")

try:
    from app.database import SessionLocal
    from app.models.watchlist import WatchlistItem
    import logging

    logging.basicConfig(level=logging.INFO)
    logger = logging.getLogger(__name__)

    def enable_all_alerts():
        """Enable all alerts for all active watchlist items."""
        db = SessionLocal()
        try:
            # Get all active (not deleted) watchlist items
            items = db.query(WatchlistItem).filter(
                WatchlistItem.is_deleted == False
            ).all()

            if not items:
                logger.warning("No active watchlist items found")
                return

            updated_count = 0
            for item in items:
                changed = False

                # Enable master alert
                if not item.alert_enabled:
                    item.alert_enabled = True
                    changed = True

                # Enable BUY alerts
                if hasattr(item, "buy_alert_enabled") and not item.buy_alert_enabled:
                    item.buy_alert_enabled = True
                    changed = True

                # Enable SELL alerts
                if hasattr(item, "sell_alert_enabled") and not item.sell_alert_enabled:
                    item.sell_alert_enabled = True
                    changed = True

                if changed:
                    updated_count += 1
                    logger.info(f"✅ Enabled alerts for {item.symbol}")

            db.commit()

            logger.info("="*60)
            logger.info(f"✅ Successfully enabled alerts for {updated_count} out of {len(items)} items")
            logger.info("="*60)

            # Show summary
            enabled_master = sum(1 for item in items if item.alert_enabled)
            enabled_buy = sum(1 for item in items if hasattr(item, "buy_alert_enabled") and item.buy_alert_enabled)
            enabled_sell = sum(1 for item in items if hasattr(item, "sell_alert_enabled") and item.sell_alert_enabled)

            logger.info("Summary:")
            logger.info(f"  - Master alert (alert_enabled): {enabled_master}/{len(items)}")
            logger.info(f"  - BUY alerts (buy_alert_enabled): {enabled_buy}/{len(items)}")
            logger.info(f"  - SELL alerts (sell_alert_enabled): {enabled_sell}/{len(items)}")

        except Exception as e:
            logger.error(f"❌ Error enabling alerts: {e}", exc_info=True)
            db.rollback()
            raise
        finally:
            db.close()

    if __name__ == "__main__":
        print("="*60)
        print("Enable All Alerts Script (Fallback)")
        print("="*60)
        print()
        enable_all_alerts()
        print("\n✅ Script completed!")

except Exception as e:
    print(f"❌ FATAL ERROR: {e}")
    import traceback
    traceback.print_exc()
