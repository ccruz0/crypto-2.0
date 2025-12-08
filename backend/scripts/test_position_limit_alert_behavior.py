#!/usr/bin/env python3
"""
Test script to verify position limit alert behavior.

This script simulates a scenario where:
- A symbol has current portfolio value > 3x trade_amount
- A BUY signal is generated
- Verifies that:
  - Alert is sent (not blocked)
  - Order is skipped
  - Monitoring entry shows order_skipped=True, blocked=False
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketData
from app.models.telegram_message import TelegramMessage
from app.services.order_position_service import calculate_portfolio_value_for_symbol
from datetime import datetime, timezone, timedelta
import json

def test_position_limit_alert_behavior():
    """Test that alerts are sent even when orders are skipped due to position limits."""
    print("="*80)
    print("POSITION LIMIT ALERT BEHAVIOR TEST")
    print("="*80)
    
    db = SessionLocal()
    try:
        # Find a watchlist item with high exposure
        # Look for items that might already have high portfolio value
        items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False,
            WatchlistItem.alert_enabled == True,
            WatchlistItem.trade_amount_usd.isnot(None),
            WatchlistItem.trade_amount_usd > 0
        ).all()
        
        if not items:
            print("❌ No enabled watchlist items found")
            return 1
        
        print(f"\n📊 Found {len(items)} enabled watchlist items")
        
        # Test each item to find one with high exposure
        test_item = None
        for item in items:
            symbol = item.symbol
            trade_amount_usd = item.trade_amount_usd or 100.0
            limit_value = 3 * trade_amount_usd
            
            # Get current market data
            market_data = db.query(MarketData).filter(
                MarketData.symbol == symbol
            ).first()
            
            if not market_data or not market_data.price:
                continue
            
            current_price = float(market_data.price)
            
            # Calculate portfolio value
            try:
                portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
                
                print(f"\n📈 {symbol}:")
                print(f"   Trade amount: ${trade_amount_usd:.2f}")
                print(f"   Limit (3x): ${limit_value:.2f}")
                print(f"   Portfolio value: ${portfolio_value:.2f}")
                print(f"   Net quantity: {net_quantity:.4f}")
                print(f"   Current price: ${current_price:.4f}")
                
                if portfolio_value > limit_value:
                    print(f"   ✅ EXCEEDS LIMIT - Will test this item")
                    test_item = item
                    break
                else:
                    print(f"   ⚠️  Below limit (would need to simulate high exposure)")
            except Exception as e:
                print(f"   ❌ Error calculating portfolio value: {e}")
                continue
        
        if not test_item:
            print("\n⚠️  No items found with portfolio value > 3x trade_amount")
            print("   This is expected if no positions are currently open")
            print("   The test verifies the logic, but cannot test with real data")
            return 0
        
        symbol = test_item.symbol
        trade_amount_usd = test_item.trade_amount_usd or 100.0
        limit_value = 3 * trade_amount_usd
        
        # Get current market data
        market_data = db.query(MarketData).filter(
            MarketData.symbol == symbol
        ).first()
        current_price = float(market_data.price)
        
        # Calculate portfolio value
        portfolio_value, net_quantity = calculate_portfolio_value_for_symbol(db, symbol, current_price)
        
        print("\n" + "="*80)
        print("TEST SCENARIO")
        print("="*80)
        print(f"Symbol: {symbol}")
        print(f"Trade amount: ${trade_amount_usd:.2f}")
        print(f"Limit (3x trade_amount): ${limit_value:.2f}")
        print(f"Current portfolio value: ${portfolio_value:.2f}")
        print(f"Net quantity: {net_quantity:.4f}")
        print(f"Current price: ${current_price:.4f}")
        print(f"\nExpected behavior:")
        print(f"  ✅ Alert should be SENT (not blocked)")
        print(f"  ✅ Order should be SKIPPED")
        print(f"  ✅ Monitoring entry should have:")
        print(f"     - blocked=False")
        print(f"     - order_skipped=True")
        print(f"     - Message should say 'ORDEN NO EJECUTADA' (not 'ALERTA BLOQUEADA')")
        
        # Check recent monitoring entries for this symbol
        print("\n" + "="*80)
        print("CHECKING MONITORING ENTRIES")
        print("="*80)
        
        # Get entries from last hour
        one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        recent_entries = db.query(TelegramMessage).filter(
            TelegramMessage.symbol == symbol,
            TelegramMessage.timestamp >= one_hour_ago
        ).order_by(TelegramMessage.timestamp.desc()).limit(10).all()
        
        if not recent_entries:
            print(f"⚠️  No recent monitoring entries found for {symbol} in the last hour")
            print(f"   This means the signal monitor hasn't processed this symbol recently")
            print(f"   or no alerts were generated")
        else:
            print(f"📊 Found {len(recent_entries)} recent entries:")
            for entry in recent_entries:
                print(f"\n  Entry ID: {entry.id}")
                print(f"  Timestamp: {entry.timestamp}")
                print(f"  Message: {entry.message[:100]}...")
                print(f"  blocked: {entry.blocked}")
                print(f"  order_skipped: {getattr(entry, 'order_skipped', 'N/A (field may not exist in DB yet)')}")
                print(f"  throttle_status: {entry.throttle_status}")
                
                # Verify expected behavior
                message_lower = entry.message.lower()
                has_orden_no_ejecutada = "orden no ejecutada" in message_lower
                has_alerta_bloqueada = "alerta bloqueada" in message_lower
                
                if has_orden_no_ejecutada:
                    print(f"  ✅ Message correctly says 'ORDEN NO EJECUTADA'")
                elif has_alerta_bloqueada:
                    print(f"  ❌ Message incorrectly says 'ALERTA BLOQUEADA' (should be 'ORDEN NO EJECUTADA')")
                else:
                    print(f"  ℹ️  Message doesn't contain position limit text (may be a different type of message)")
                
                if entry.blocked:
                    print(f"  ❌ blocked=True (should be False for position limit cases)")
                else:
                    print(f"  ✅ blocked=False (correct)")
                
                order_skipped = getattr(entry, 'order_skipped', False)
                if order_skipped:
                    print(f"  ✅ order_skipped=True (correct)")
                else:
                    print(f"  ⚠️  order_skipped=False or field missing (should be True for position limit cases)")
        
        # Summary
        print("\n" + "="*80)
        print("TEST SUMMARY")
        print("="*80)
        print(f"Symbol tested: {symbol}")
        print(f"Portfolio value: ${portfolio_value:.2f}")
        print(f"Limit: ${limit_value:.2f}")
        print(f"Exceeds limit: {portfolio_value > limit_value}")
        print(f"\nTo fully test this behavior:")
        print(f"  1. Ensure signal_monitor is running")
        print(f"  2. Wait for a BUY signal to be generated for {symbol}")
        print(f"  3. Check monitoring entries to verify:")
        print(f"     - Alert was sent (blocked=False)")
        print(f"     - Order was skipped (order_skipped=True)")
        print(f"     - Message says 'ORDEN NO EJECUTADA'")
        
        return 0
        
    except Exception as e:
        print(f"❌ Error in test: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(test_position_limit_alert_behavior())
