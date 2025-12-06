#!/usr/bin/env python3
"""Diagnose why BUY orders are not being created"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.signal_monitor import SignalMonitorService
from app.api.routes_signals import get_signals
from datetime import datetime, timedelta, timezone
from sqlalchemy import or_, func

def diagnose_buy_orders():
    db = SessionLocal()
    try:
        # Get all watchlist items with alert_enabled = true
        watchlist_items = db.query(WatchlistItem).filter(
            WatchlistItem.alert_enabled == True,
            WatchlistItem.is_deleted == False
        ).all()
        
        print(f"\n📊 Found {len(watchlist_items)} coins with alert_enabled = true\n")
        
        signal_monitor = SignalMonitorService()
        
        for item in watchlist_items:
            symbol = item.symbol
            print(f"\n{'='*80}")
            print(f"🔍 Analyzing {symbol}")
            print(f"{'='*80}")
            
            # Check basic configuration
            print(f"✅ Configuration:")
            print(f"   - alert_enabled: {item.alert_enabled}")
            print(f"   - trade_enabled: {item.trade_enabled}")
            print(f"   - trade_amount_usd: ${item.trade_amount_usd or 0}")
            print(f"   - min_price_change_pct: {item.min_price_change_pct or 'default (3.0%)'}")
            
            if not item.trade_enabled:
                print(f"\n❌ BLOCKED: trade_enabled = False")
                continue
                
            if not item.trade_amount_usd or item.trade_amount_usd <= 0:
                print(f"\n❌ BLOCKED: trade_amount_usd not configured")
                continue
            
            # Get current signals
            try:
                signals_data = get_signals("CRYPTO_COM", symbol)
                if not signals_data:
                    print(f"\n❌ BLOCKED: No signal data available")
                    continue
                    
                buy_signal = signals_data.get("buy_signal", False)
                current_price = signals_data.get("price", 0)
                rsi = signals_data.get("rsi")
                
                print(f"\n📈 Current Signals:")
                print(f"   - buy_signal: {buy_signal}")
                print(f"   - current_price: ${current_price:.4f}")
                print(f"   - RSI: {rsi}")
                
                if not buy_signal:
                    print(f"\n❌ BLOCKED: No BUY signal detected")
                    continue
                    
            except Exception as e:
                print(f"\n❌ ERROR getting signals: {e}")
                continue
            
            # Check for recent orders
            recent_threshold = datetime.now(timezone.utc) - timedelta(minutes=5)
            recent_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                or_(
                    ExchangeOrder.exchange_create_time >= recent_threshold,
                    ExchangeOrder.created_at >= recent_threshold
                )
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            ).all()
            
            print(f"\n📋 Recent Orders (last 5 minutes): {len(recent_orders)}")
            if recent_orders:
                for order in recent_orders[:3]:
                    order_time = order.exchange_create_time or order.created_at
                    print(f"   - Order {order.exchange_order_id}: {order.status.value} at {order_time}")
            
            # Check open orders
            open_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
            ).all()
            
            print(f"\n📋 Open Orders: {len(open_orders)}/{signal_monitor.MAX_OPEN_ORDERS_PER_SYMBOL}")
            if len(open_orders) >= signal_monitor.MAX_OPEN_ORDERS_PER_SYMBOL:
                print(f"   ❌ BLOCKED: Maximum open orders limit reached")
                continue
            
            # Check last order price
            all_recent_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
            last_order = db.query(ExchangeOrder).filter(
                ExchangeOrder.symbol == symbol,
                ExchangeOrder.side == OrderSideEnum.BUY,
                or_(
                    ExchangeOrder.exchange_create_time >= all_recent_threshold,
                    ExchangeOrder.created_at >= all_recent_threshold
                )
            ).order_by(
                func.coalesce(ExchangeOrder.exchange_create_time, ExchangeOrder.created_at).desc()
            ).first()
            
            if last_order:
                last_price = float(last_order.price or last_order.avg_price or last_order.filled_price or 0)
                print(f"\n💰 Last Order Price: ${last_price:.4f}")
                
                if last_price > 0:
                    min_price_change = item.min_price_change_pct or signal_monitor.MIN_PRICE_CHANGE_PCT
                    price_change_pct = abs((current_price - last_price) / last_price * 100)
                    print(f"   - Price change: {price_change_pct:.2f}%")
                    print(f"   - Required: {min_price_change:.2f}%")
                    
                    if price_change_pct < min_price_change:
                        print(f"   ❌ BLOCKED: Price change {price_change_pct:.2f}% < {min_price_change:.2f}% required")
                        continue
                    else:
                        print(f"   ✅ Price change requirement met")
            else:
                print(f"\n💰 Last Order Price: None (first order)")
            
            # Check alert throttling
            if last_order and last_order.price:
                last_price = float(last_order.price or last_order.avg_price or last_order.filled_price or 0)
                if last_price > 0:
                    should_send, reason = signal_monitor.should_send_alert(
                        symbol, "BUY", current_price, 
                        trade_enabled=item.trade_enabled,
                        min_price_change_pct=item.min_price_change_pct
                    )
                    print(f"\n🔔 Alert Throttling:")
                    print(f"   - should_send: {should_send}")
                    print(f"   - reason: {reason}")
            
            print(f"\n✅ All checks passed! Order should be created.")
            
    finally:
        db.close()

if __name__ == "__main__":
    diagnose_buy_orders()

