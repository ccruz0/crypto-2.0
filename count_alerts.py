#!/usr/bin/env python3
"""
Count how many coins have BUY/SELL alerts enabled.

This script queries the database and reports:
- Total watchlist items
- Items with BUY alerts enabled
- Items with SELL alerts enabled
- Items with both BUY and SELL alerts enabled
- Items with TRADE enabled
"""

import sys
import os

# Add backend directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def count_alerts():
    """Count coins with alerts enabled"""
    db = SessionLocal()
    
    try:
        # Get all active watchlist items (not deleted)
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        if not items:
            print("No watchlist items found")
            return
        
        total = len(items)
        buy_alerts_yes = 0
        sell_alerts_yes = 0
        both_alerts_yes = 0
        trade_yes = 0
        
        buy_alert_coins = []
        sell_alert_coins = []
        both_alert_coins = []
        trade_coins = []
        
        for item in items:
            has_buy = getattr(item, "buy_alert_enabled", False)
            has_sell = getattr(item, "sell_alert_enabled", False)
            has_trade = item.trade_enabled
            
            if has_buy:
                buy_alerts_yes += 1
                buy_alert_coins.append(item.symbol)
            
            if has_sell:
                sell_alerts_yes += 1
                sell_alert_coins.append(item.symbol)
            
            if has_buy and has_sell:
                both_alerts_yes += 1
                both_alert_coins.append(item.symbol)
            
            if has_trade:
                trade_yes += 1
                trade_coins.append(item.symbol)
        
        print("=" * 60)
        print("ALERT STATUS SUMMARY")
        print("=" * 60)
        print(f"\nTotal watchlist items: {total}")
        print(f"\nBUY Alerts Enabled: {buy_alerts_yes} coins")
        print(f"SELL Alerts Enabled: {sell_alerts_yes} coins")
        print(f"Both BUY & SELL Enabled: {both_alerts_yes} coins")
        print(f"TRADE Enabled: {trade_yes} coins")
        
        print(f"\n{'─' * 60}")
        print("Coins with BUY alerts enabled:")
        if buy_alert_coins:
            print(f"  {', '.join(buy_alert_coins)}")
        else:
            print("  None")
        
        print(f"\nCoins with SELL alerts enabled:")
        if sell_alert_coins:
            print(f"  {', '.join(sell_alert_coins)}")
        else:
            print("  None")
        
        print(f"\nCoins with BOTH alerts enabled:")
        if both_alert_coins:
            print(f"  {', '.join(both_alert_coins)}")
        else:
            print("  None")
        
        print(f"\nCoins with TRADE enabled:")
        if trade_coins:
            print(f"  {', '.join(trade_coins)}")
        else:
            print("  None")
        
        print("=" * 60)
        
    except Exception as e:
        logger.error(f"❌ Error counting alerts: {e}", exc_info=True)
        raise
    finally:
        db.close()


if __name__ == "__main__":
    try:
        count_alerts()
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)





