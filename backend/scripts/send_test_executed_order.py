#!/usr/bin/env python3
"""
Quick script to send a test executed order notification with the new format.
Run this from the backend directory: python scripts/send_test_executed_order.py
"""
import sys
import os

# Add backend to path
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, backend_dir)

from app.services.telegram_notifier import telegram_notifier

def main():
    """Send a test executed order notification"""
    
    print("🧪 Sending test executed order notification with new format...\n")
    
    # Example: SL/TP order triggered by alert
    result = telegram_notifier.send_executed_order(
        symbol="ETH_USDT",
        side="SELL",
        price=2500.0,
        quantity=0.1,
        total_usd=250.0,
        order_id="TEST_ORDER_001",
        order_type="STOP_LIMIT",
        entry_price=2600.0,  # Entry price for profit/loss calculation
        order_role="STOP_LOSS",  # This is a Stop Loss order
        trade_signal_id=123,  # Created by alert
        parent_order_id=None
    )
    
    if result:
        print("✅ Test notification sent successfully!")
        print("\nThe message should show:")
        print("   🎯 Origen: 🛑 Stop Loss (triggered by 📢 Alerta)")
    else:
        print("❌ Failed to send notification")
        print("   Check if Telegram is enabled and configured correctly")

if __name__ == "__main__":
    main()






