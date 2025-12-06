#!/usr/bin/env python3
"""
Diagnostic script to investigate why margin orders are failing with error 306.
Checks:
1. Account balances (USD/USDT)
2. Pending orders that might block margin
3. Margin calculations for pending orders
4. Recent margin order failures
"""

import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.exchange_order import ExchangeOrder, OrderStatusEnum, OrderSideEnum
from app.services.brokers.crypto_com_trade import trade_client
import json
from datetime import datetime, timedelta, timezone

def main():
    db = SessionLocal()
    try:
        print("=" * 80)
        print("MARGIN ORDER DIAGNOSTIC REPORT")
        print("=" * 80)
        print()
        
        # 1. Get account summary
        print("1. ACCOUNT BALANCES")
        print("-" * 80)
        try:
            summary = trade_client.get_account_summary()
            if 'accounts' in summary:
                usd_balance = 0
                usdt_balance = 0
                for acc in summary['accounts']:
                    currency = acc.get('currency', '').upper()
                    balance = float(acc.get('balance', '0') or '0')
                    available = float(acc.get('available', '0') or '0')
                    if currency == 'USD':
                        usd_balance = balance
                        usd_available = available
                        print(f"  USD: balance={balance:,.2f}, available={available:,.2f}")
                    elif currency == 'USDT':
                        usdt_balance = balance
                        usdt_available = available
                        print(f"  USDT: balance={balance:,.2f}, available={available:,.2f}")
                print(f"  Total USD equivalent: ${usd_balance + usdt_balance:,.2f}")
                print(f"  Total available: ${usd_available + usdt_available:,.2f}")
            else:
                print(f"  Unexpected summary format: {list(summary.keys())}")
        except Exception as e:
            print(f"  ❌ Error getting account summary: {e}")
        
        print()
        
        # 2. Check pending orders
        print("2. PENDING ORDERS (that might block margin)")
        print("-" * 80)
        pending_statuses = [OrderStatusEnum.NEW, OrderStatusEnum.ACTIVE, OrderStatusEnum.PARTIALLY_FILLED]
        pending_orders = db.query(ExchangeOrder).filter(
            ExchangeOrder.status.in_(pending_statuses)
        ).all()
        
        print(f"  Total pending orders: {len(pending_orders)}")
        
        if pending_orders:
            buy_orders = [o for o in pending_orders if o.side == OrderSideEnum.BUY]
            sell_orders = [o for o in pending_orders if o.side == OrderSideEnum.SELL]
            print(f"  BUY orders: {len(buy_orders)}")
            print(f"  SELL orders: {len(sell_orders)}")
            
            # Calculate margin blocked by BUY orders
            total_notional = 0
            total_margin_required = 0
            by_symbol = {}
            
            for order in buy_orders:
                symbol = order.symbol
                if symbol not in by_symbol:
                    by_symbol[symbol] = []
                
                notional = 0
                if order.notional:
                    notional = float(order.notional)
                elif order.price and order.quantity:
                    notional = float(order.price) * float(order.quantity)
                
                leverage = 10  # Default
                if hasattr(order, 'leverage') and order.leverage:
                    leverage = float(order.leverage)
                margin_required = notional / leverage if leverage > 0 else notional
                
                total_notional += notional
                total_margin_required += margin_required
                
                by_symbol[symbol].append({
                    'notional': notional,
                    'margin': margin_required,
                    'leverage': leverage,
                    'type': order.order_type
                })
            
            print()
            print(f"  Total BUY notional: ${total_notional:,.2f}")
            print(f"  Total margin required (at avg leverage): ${total_margin_required:,.2f}")
            print()
            
            if by_symbol:
                print("  By symbol:")
                for symbol, orders in sorted(by_symbol.items()):
                    sym_notional = sum(o['notional'] for o in orders)
                    sym_margin = sum(o['margin'] for o in orders)
                    avg_leverage = sum(o['leverage'] for o in orders) / len(orders) if orders else 10
                    print(f"    {symbol}: {len(orders)} order(s), ${sym_notional:,.2f} notional, ${sym_margin:,.2f} margin @ {avg_leverage:.1f}x")
        else:
            print("  ✅ No pending orders")
        
        print()
        
        # 3. Recent margin order failures
        print("3. RECENT MARGIN ORDER FAILURES (last 24h)")
        print("-" * 80)
        threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        # Check if leverage column exists
        try:
            failed_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.created_at >= threshold,
                ExchangeOrder.side == OrderSideEnum.BUY
            ).all()
            # Filter manually for orders with leverage in notes or other fields
            margin_failures = []
            for order in failed_orders:
                # Check if order failed and might be margin order
                if order.status not in [OrderStatusEnum.FILLED, OrderStatusEnum.PARTIALLY_FILLED]:
                    # Try to get leverage from notes or other fields
                    leverage = 10  # Default
                    if hasattr(order, 'leverage') and order.leverage:
                        leverage = float(order.leverage)
                    margin_failures.append({
                        'symbol': order.symbol,
                        'notional': float(order.notional) if order.notional else 0,
                        'leverage': leverage,
                        'status': order.status.value,
                        'created': order.created_at
                    })
        except Exception as e:
            print(f"  Note: Could not query leverage column: {e}")
            margin_failures = []
        
        margin_failures = []
        for order in failed_orders:
            # Check if order failed (status is not FILLED)
            if order.status not in [OrderStatusEnum.FILLED, OrderStatusEnum.PARTIALLY_FILLED]:
                notional = float(order.notional) if order.notional else 0
                leverage = float(order.leverage) if order.leverage else 10
                margin_req = notional / leverage if leverage > 0 else notional
                margin_failures.append({
                    'symbol': order.symbol,
                    'notional': notional,
                    'margin_req': margin_req,
                    'leverage': leverage,
                    'status': order.status.value,
                    'created': order.created_at
                })
        # Reuse margin_failures from above
        
        if margin_failures:
            print(f"  Found {len(margin_failures)} failed margin orders:")
            for fail in margin_failures[:10]:  # Show first 10
                print(f"    {fail['symbol']}: ${fail['notional']:,.2f} notional, ${fail['margin_req']:,.2f} margin required @ {fail['leverage']}x, status={fail['status']}")
        else:
            print("  No recent margin order failures found")
        
        print()
        
        # 4. Analysis
        print("4. ANALYSIS")
        print("-" * 80)
        print("  Possible causes of error 306 (INSUFFICIENT_AVAILABLE_BALANCE):")
        print("    1. Total margin required by pending orders exceeds available balance")
        print("    2. Crypto.com requires additional margin buffer (beyond notional/leverage)")
        print("    3. Some margin is locked for existing positions")
        print("    4. Minimum margin requirements per order (Crypto.com might require $X minimum)")
        print()
        print("  Recommendations:")
        if total_margin_required > 0:
            print(f"    - Check if total margin required (${total_margin_required:,.2f}) exceeds available balance")
            print(f"    - Consider canceling some pending orders to free up margin")
        print("    - Try placing a smaller order (e.g., $100 instead of $1000)")
        print("    - Verify margin trading is enabled on your Crypto.com account")
        print("    - Check Crypto.com Exchange dashboard for margin usage details")
        
    finally:
        db.close()

if __name__ == "__main__":
    main()

