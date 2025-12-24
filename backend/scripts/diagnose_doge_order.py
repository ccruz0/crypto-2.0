#!/usr/bin/env python3
"""
Diagnostic script to check why DOGE_USDT signal didn't create an order.

This script checks:
1. Watchlist configuration (trade_enabled, trade_amount_usd, alert_enabled, buy_alert_enabled)
2. Recent signal events for DOGE_USDT
3. Recent logs related to DOGE_USDT order creation
4. Current open orders for DOGE
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.trade_signal import TradeSignal
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from sqlalchemy import desc
from datetime import datetime, timedelta

def diagnose_doge_order():
    """Diagnose why DOGE_USDT didn't create an order"""
    db = SessionLocal()
    
    try:
        symbol = "DOGE_USDT"
        print(f"\n{'='*60}")
        print(f"🔍 DIAGNOSIS: Why {symbol} didn't create an order")
        print(f"{'='*60}\n")
        
        # 1. Check watchlist configuration
        print("1️⃣ WATCHLIST CONFIGURATION:")
        print("-" * 60)
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.is_deleted == False
        ).first()
        
        if not watchlist_item:
            print(f"❌ {symbol} NOT FOUND in watchlist!")
            print("   → This is the problem! Add it to the watchlist first.")
            return
        
        print(f"✅ {symbol} found in watchlist")
        print(f"   - alert_enabled: {watchlist_item.alert_enabled}")
        print(f"   - buy_alert_enabled: {getattr(watchlist_item, 'buy_alert_enabled', None)}")
        print(f"   - trade_enabled: {watchlist_item.trade_enabled}")
        print(f"   - trade_amount_usd: {watchlist_item.trade_amount_usd}")
        print(f"   - sl_tp_mode: {watchlist_item.sl_tp_mode}")
        
        # Check what's blocking
        issues = []
        if not watchlist_item.alert_enabled:
            issues.append("❌ alert_enabled=False (alerts disabled)")
        if not getattr(watchlist_item, 'buy_alert_enabled', False):
            issues.append("❌ buy_alert_enabled=False (BUY alerts disabled)")
        if not watchlist_item.trade_enabled:
            issues.append("❌ trade_enabled=False (trading disabled - THIS BLOCKS ORDERS)")
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            issues.append(f"❌ trade_amount_usd={watchlist_item.trade_amount_usd} (not configured - THIS BLOCKS ORDERS)")
        
        if issues:
            print(f"\n⚠️  ISSUES FOUND:")
            for issue in issues:
                print(f"   {issue}")
        else:
            print(f"\n✅ All watchlist flags are correctly configured!")
        
        # 2. Check recent signal events
        print(f"\n2️⃣ RECENT SIGNAL EVENTS:")
        print("-" * 60)
        recent_signals = db.query(TradeSignal).filter(
            TradeSignal.symbol == symbol
        ).order_by(desc(TradeSignal.created_at)).limit(5).all()
        
        if recent_signals:
            for signal in recent_signals:
                print(f"   - {signal.created_at}: {signal.side} @ ${signal.price:.4f}")
                print(f"     Source: {signal.source}, Emit reason: {signal.emit_reason}")
        else:
            print(f"   ⚠️  No signal events found for {symbol}")
        
        # 3. Check recent orders
        print(f"\n3️⃣ RECENT ORDERS:")
        print("-" * 60)
        recent_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol
        ).order_by(desc(ExchangeOrder.created_at)).limit(5).all()
        
        if recent_orders:
            for order in recent_orders:
                status_emoji = "✅" if order.status == OrderStatusEnum.FILLED else "⏳" if order.status in [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE] else "❌"
                print(f"   {status_emoji} {order.created_at}: {order.side.value} {order.type.value} @ ${order.price:.4f} - {order.status.value}")
        else:
            print(f"   ⚠️  No orders found for {symbol}")
        
        # 4. Check open orders count
        print(f"\n4️⃣ OPEN ORDERS COUNT:")
        print("-" * 60)
        base_symbol = symbol.split('_')[0]  # DOGE from DOGE_USDT
        open_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol.like(f"{base_symbol}_%"),
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status.in_([OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED])
        ).count()
        print(f"   Open BUY orders for {base_symbol}: {open_orders}/3 (max allowed)")
        
        if open_orders >= 3:
            print(f"   ⚠️  MAX OPEN ORDERS REACHED - This would block new orders!")
        
        # 5. Summary and recommendations
        print(f"\n{'='*60}")
        print("📋 SUMMARY & RECOMMENDATIONS:")
        print(f"{'='*60}\n")
        
        if not watchlist_item.trade_enabled:
            print("🔧 FIX: Enable trading for DOGE_USDT")
            print("   1. Go to Dashboard")
            print("   2. Find DOGE_USDT in the watchlist")
            print("   3. Enable 'Trade' toggle")
            print("   4. Set 'Amount USD' (e.g., 100)")
        
        if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
            print("🔧 FIX: Configure trade amount")
            print("   1. Go to Dashboard")
            print("   2. Find DOGE_USDT in the watchlist")
            print("   3. Set 'Amount USD' field (e.g., 100)")
        
        if watchlist_item.trade_enabled and watchlist_item.trade_amount_usd and watchlist_item.trade_amount_usd > 0:
            print("✅ Configuration looks correct!")
            print("   If orders still aren't being created, check:")
            print("   - Backend logs for error messages")
            print("   - Missing MA indicators (MA50, EMA10)")
            print("   - Portfolio value limits")
            print("   - Live trading status")
        
    except Exception as e:
        print(f"❌ Error during diagnosis: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    diagnose_doge_order()


