#!/usr/bin/env python3
"""
Script to verify if orders are real or simulated by checking:
1. LIVE_TRADING status
2. Order IDs format (dry_run vs real)
3. Whether orders exist in exchange API
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
from app.utils.live_trading import get_live_trading_status
from app.services.brokers.crypto_com_trade import trade_client
from datetime import datetime, timedelta

def check_live_trading_status():
    """Check if LIVE_TRADING is enabled"""
    db = SessionLocal()
    try:
        live_trading = get_live_trading_status(db)
        return live_trading
    finally:
        db.close()

def check_order_ids():
    """Check if order IDs look like dry_run IDs"""
    db = SessionLocal()
    try:
        # Get recent executed orders
        recent_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status == OrderStatusEnum.FILLED
        ).order_by(ExchangeOrder.updated_at.desc()).limit(10).all()
        
        dry_run_patterns = []
        real_orders = []
        
        for order in recent_orders:
            order_id = order.exchange_order_id
            if order_id and (order_id.startswith("dry_") or order_id.startswith("dry_market_") or order_id.startswith("dry_client_")):
                dry_run_patterns.append({
                    "order_id": order_id,
                    "symbol": order.symbol,
                    "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                    "created_at": order.created_at
                })
            else:
                real_orders.append({
                    "order_id": order_id,
                    "symbol": order.symbol,
                    "side": order.side.value if hasattr(order.side, 'value') else str(order.side),
                    "created_at": order.created_at
                })
        
        return dry_run_patterns, real_orders
    finally:
        db.close()

def verify_orders_in_exchange(order_ids):
    """Check if order IDs exist in the exchange API"""
    verified = []
    not_found = []
    
    for order_id in order_ids[:5]:  # Limit to 5 to avoid rate limits
        try:
            # Try to get order details from exchange
            # Note: Crypto.com might not have a direct "get order by ID" endpoint
            # So we'll check order history instead
            history = trade_client.get_order_history(page_size=50, page=0)
            
            if history and "data" in history:
                order_list = history.get("data", {}).get("order_list", [])
                found = any(order.get("order_id") == order_id for order in order_list)
                
                if found:
                    verified.append(order_id)
                else:
                    not_found.append(order_id)
            else:
                not_found.append(order_id)
        except Exception as e:
            print(f"Error checking order {order_id}: {e}")
            not_found.append(order_id)
    
    return verified, not_found

def main():
    print("=" * 60)
    print("ORDER REALITY VERIFICATION")
    print("=" * 60)
    print()
    
    # 1. Check LIVE_TRADING status
    print("1. Checking LIVE_TRADING status...")
    live_trading = check_live_trading_status()
    status_emoji = "✅" if live_trading else "❌"
    print(f"   {status_emoji} LIVE_TRADING: {live_trading}")
    if not live_trading:
        print("   ⚠️  WARNING: LIVE_TRADING is DISABLED - orders are in DRY_RUN mode!")
    print()
    
    # 2. Check order IDs
    print("2. Analyzing recent order IDs...")
    dry_run_orders, real_orders = check_order_ids()
    
    print(f"   Found {len(dry_run_orders)} orders with DRY_RUN pattern")
    print(f"   Found {len(real_orders)} orders with real-looking IDs")
    print()
    
    if dry_run_orders:
        print("   ⚠️  DRY_RUN orders detected:")
        for order in dry_run_orders[:3]:
            print(f"      - {order['order_id']} ({order['symbol']} {order['side']})")
        print()
    
    if real_orders:
        print("   📋 Recent real-looking orders:")
        for order in real_orders[:5]:
            print(f"      - {order['order_id']} ({order['symbol']} {order['side']}) at {order['created_at']}")
        print()
        
        # 3. Try to verify with exchange
        print("3. Verifying orders with Crypto.com Exchange API...")
        order_ids_to_check = [o['order_id'] for o in real_orders[:5]]
        verified, not_found = verify_orders_in_exchange(order_ids_to_check)
        
        if verified:
            print(f"   ✅ {len(verified)} order(s) found in exchange:")
            for order_id in verified:
                print(f"      - {order_id}")
        print()
        
        if not_found:
            print(f"   ⚠️  {len(not_found)} order(s) NOT found in exchange:")
            for order_id in not_found:
                print(f"      - {order_id}")
            print()
            print("   💡 This could mean:")
            print("      - Orders are from a different API key/account")
            print("      - Orders are older than the history window")
            print("      - Orders were simulated but saved to database")
    
    print()
    print("=" * 60)
    print("RECOMMENDATIONS:")
    print("=" * 60)
    
    if not live_trading:
        print("1. ⚠️  Enable LIVE_TRADING if you want real orders")
        print("   - Check database: SELECT * FROM trading_settings WHERE setting_key='LIVE_TRADING';")
        print("   - Or set environment variable: LIVE_TRADING=true")
    
    if dry_run_orders:
        print("2. ⚠️  You have DRY_RUN orders in your database")
        print("   - These are simulated and never sent to the exchange")
    
    if real_orders and not_found:
        print("3. ⚠️  Some orders with real-looking IDs are not in the exchange")
        print("   - Verify you're checking the correct Crypto.com account")
        print("   - Check if API credentials match the account you're viewing")
        print("   - Orders might be from a different API key")
    
    print()
    print("=" * 60)

if __name__ == "__main__":
    main()

