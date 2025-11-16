#!/usr/bin/env python3
"""
Diagnostic script to check why a test order was not executed.
This script checks:
1. Recent logs for simulate-alert endpoint
2. SOL_USDT configuration in watchlist
3. Order creation errors
4. Recent orders in database
"""
import sys
import os
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.exchange_order import ExchangeOrder
from datetime import datetime, timedelta

def main():
    db = SessionLocal()
    symbol = "SOL_USDT"
    
    try:
        print("="*80)
        print("DIAGNOSTIC: Why test order was not executed")
        print("="*80)
        
        # 1. Check watchlist configuration
        print(f"\n1. CHECKING WATCHLIST CONFIGURATION FOR {symbol}")
        print("-"*80)
        watchlist_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol
        ).first()
        
        if not watchlist_item:
            print(f"❌ {symbol} NOT FOUND in watchlist")
            print("   → This is the problem! Add SOL_USDT to watchlist first.")
            return 1
        
        print(f"✅ {symbol} found in watchlist")
        print(f"   - Trade Enabled: {'✅ YES' if watchlist_item.trade_enabled else '❌ NO'}")
        print(f"   - Alert Enabled: {'✅ YES' if watchlist_item.alert_enabled else '❌ NO'}")
        print(f"   - Amount USD: ${watchlist_item.trade_amount_usd:,.2f}" if watchlist_item.trade_amount_usd else "   - Amount USD: ❌ NOT CONFIGURED")
        print(f"   - Margin: {'✅ YES' if watchlist_item.trade_on_margin else '❌ NO'}")
        print(f"   - Is Deleted: {'❌ YES (PROBLEM!)' if watchlist_item.is_deleted else '✅ NO'}")
        
        # Check conditions
        can_create_order = (
            watchlist_item.trade_enabled and
            watchlist_item.trade_amount_usd and
            watchlist_item.trade_amount_usd > 0 and
            not watchlist_item.is_deleted
        )
        
        if not can_create_order:
            print(f"\n❌ CONDITIONS NOT MET FOR ORDER CREATION:")
            if not watchlist_item.trade_enabled:
                print(f"   - Trade Enabled = NO (must be YES)")
            if not watchlist_item.trade_amount_usd or watchlist_item.trade_amount_usd <= 0:
                print(f"   - Amount USD not configured or <= 0")
            if watchlist_item.is_deleted:
                print(f"   - Symbol is marked as deleted")
            return 1
        
        print(f"\n✅ ALL CONDITIONS MET - Order should be created")
        
        # 2. Check recent orders
        print(f"\n2. CHECKING RECENT ORDERS FOR {symbol}")
        print("-"*80)
        recent_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.symbol == symbol
        ).order_by(ExchangeOrder.exchange_create_time.desc()).limit(5).all()
        
        if not recent_orders:
            print(f"⚠️  No orders found for {symbol} in database")
            print(f"   → This confirms the order was NOT created")
        else:
            print(f"✅ Found {len(recent_orders)} recent order(s):")
            for order in recent_orders:
                print(f"   - Order ID: {order.exchange_order_id}")
                print(f"     Status: {order.status}")
                print(f"     Side: {order.side}")
                print(f"     Type: {order.order_type}")
                print(f"     Created: {order.exchange_create_time}")
                print(f"     Price: {order.price}")
                print()
        
        # 3. Check for errors in logs (we'll provide instructions)
        print(f"\n3. LOG ANALYSIS INSTRUCTIONS")
        print("-"*80)
        print("Run these commands on AWS server to check logs:")
        print()
        print("# Check simulate-alert endpoint calls:")
        print('docker compose logs backend-aws 2>&1 | grep -i "simulate-alert" | tail -30')
        print()
        print("# Check order creation attempts:")
        print('docker compose logs backend-aws 2>&1 | grep -E "(Trade enabled|creating BUY order|ORDER CREATION)" | tail -30')
        print()
        print("# Check for errors:")
        print('docker compose logs backend-aws 2>&1 | grep -i "error\|failed\|exception" | grep -i "SOL_USDT\|order" | tail -30')
        print()
        print("# Check recent backend logs:")
        print('docker compose logs backend-aws --tail 100 | grep -i "SOL_USDT\|simulate\|test"')
        
        # 4. Summary
        print(f"\n4. SUMMARY")
        print("-"*80)
        if can_create_order:
            print("✅ Configuration is correct")
            print("❌ Order was not created (check logs for errors)")
            print("\nPossible causes:")
            print("   1. Error in order creation logic")
            print("   2. Exchange API error")
            print("   3. Dry run mode (LIVE_TRADING=false)")
            print("   4. Event loop conflict (asyncio issue)")
        else:
            print("❌ Configuration issue detected")
            print("   Fix the configuration issues listed above")
        
        print("\n" + "="*80)
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

