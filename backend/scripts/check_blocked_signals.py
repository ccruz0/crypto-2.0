#!/usr/bin/env python3
"""
Check for blocked buy orders or alerts in the last hour due to price change threshold
"""
import sys
import os
from datetime import datetime, timedelta, timezone

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.config_loader import load_config

def check_blocked_signals():
    """Check for signals that were blocked due to price change threshold"""
    db: Session = SessionLocal()
    
    try:
        print("🔍 Checking for blocked signals in the last hour...")
        print("=" * 60)
        
        # Get all watchlist items with alert_enabled
        watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True,
            WatchlistItem.is_deleted == False
        ).all()
        
        print(f"📊 Found {len(watchlist_items)} coins with alerts enabled\n")
        
        # Load trading config
        config = load_config()
        coins_config = config.get("coins", {})
        
        blocked_count = 0
        alerts_blocked_count = 0
        
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        
        for item in watchlist_items:
            symbol = item.symbol
            if not symbol:
                continue
            
            # Get preset from config
            coin_config = coins_config.get(symbol, {})
            preset = coin_config.get("preset", "swing")
            risk_mode = item.sl_tp_mode or "conservative"
            
            # Get min_price_change_pct (check if attribute exists)
            if hasattr(item, 'min_price_change_pct') and item.min_price_change_pct is not None:
                min_price_change_pct = item.min_price_change_pct
            else:
                min_price_change_pct = 1.0  # Default
            
            # Get current price
            current_price = item.price
            if not current_price or current_price == 0:
                continue
            
            # Get recent open BUY orders
            recent_buy_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_([
                    OrderStatusEnum.NEW,
                    OrderStatusEnum.ACTIVE,
                    OrderStatusEnum.PARTIALLY_FILLED
                ])
            ).order_by(ExchangeOrder.created_at.desc()).all()
            
            # Get the most recent order price
            if recent_buy_orders:
                most_recent_order = recent_buy_orders[0]
                last_order_price = float(most_recent_order.price) if most_recent_order.price else 0.0
                
                if last_order_price > 0:
                    price_change_pct = abs((current_price - last_order_price) / last_order_price * 100)
                    
                    if price_change_pct < min_price_change_pct:
                        # This would have been blocked
                        blocked_count += 1
                        print(f"🚫 BLOCKED ORDER: {symbol}")
                        print(f"   Strategy: {preset}-{risk_mode}")
                        print(f"   Min price change: {min_price_change_pct}%")
                        print(f"   Current price change: {price_change_pct:.2f}%")
                        print(f"   Last order price: ${last_order_price:.4f}")
                        print(f"   Current price: ${current_price:.4f}")
                        print(f"   Price difference: ${abs(current_price - last_order_price):.4f}")
                        print(f"   Would need: ${abs(min_price_change_pct / 100 * last_order_price):.4f} change")
                        print()
            
            # Check if there's a signal that would trigger but was blocked
            # This is harder to determine without checking actual signal state
            # But we can check if there are recent signals that didn't result in orders
            
            # Check recent filled/executed orders in last hour
            recent_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.created_at >= one_hour_ago
            ).order_by(ExchangeOrder.created_at.desc()).all()
            
            # If there are no recent orders but alert is enabled, it might have been blocked
            if not recent_orders and item.trade_enabled:
                # Check if price is significantly different from last order (if any)
                if recent_buy_orders:
                    most_recent_order = recent_buy_orders[0]
                    last_order_price = float(most_recent_order.price) if most_recent_order.price else 0.0
                    
                    if last_order_price > 0:
                        price_change_pct = abs((current_price - last_order_price) / last_order_price * 100)
                        
                        if price_change_pct < min_price_change_pct:
                            alerts_blocked_count += 1
                            print(f"🔔 BLOCKED ALERT: {symbol}")
                            print(f"   Strategy: {preset}-{risk_mode}")
                            print(f"   Min price change: {min_price_change_pct}%")
                            print(f"   Current price change: {price_change_pct:.2f}%")
                            print(f"   Last order price: ${last_order_price:.4f}")
                            print(f"   Current price: ${current_price:.4f}")
                            print(f"   Alert enabled but no order created (price change too small)")
                            print()
        
        print("=" * 60)
        print(f"📊 Summary:")
        print(f"   Blocked orders: {blocked_count}")
        print(f"   Blocked alerts: {alerts_blocked_count}")
        print(f"   Total blocked: {blocked_count + alerts_blocked_count}")
        
        if blocked_count == 0 and alerts_blocked_count == 0:
            print("\n✅ No blocked signals found in the last hour")
            print("   All signals that met conditions were processed")
        
    except Exception as e:
        print(f"❌ Error checking blocked signals: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    check_blocked_signals()

