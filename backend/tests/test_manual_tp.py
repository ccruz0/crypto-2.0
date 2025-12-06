#!/usr/bin/env python3
"""
Test script to manually trigger TP creation and verify HTTP logging.
This simulates what happens when a manual TP is created from the dashboard.

VERIFICATION:
1. Run the test:
   docker compose exec backend-aws python3 /app/tests/test_manual_tp.py

2. Check logs:
   docker compose logs backend-aws 2>&1 | grep "TP_ORDER" | tail -50

Expected logs:
- [TP_ORDER][TEST] Sanity check log before placing TP order
- [TP_ORDER][MANUAL] Sending HTTP request to exchange
- [TP_ORDER][MANUAL] Payload JSON: ...
- [TP_ORDER][MANUAL] Received HTTP response from exchange
- FULL PAYLOAD: ...
"""
import sys
import os
sys.path.insert(0, '/app')

# IMPORTANT: Setup logging BEFORE importing any modules that use logging
from app.core.logging_config import setup_logging, get_tp_logger

# Configure logging to ensure logs appear in Docker
setup_logging()

# Get dedicated TP logger for test verification
logger = get_tp_logger()

from app.database import SessionLocal
from app.services.tp_sl_order_creator import create_take_profit_order

def main():
    """Test manual TP creation"""
    db = SessionLocal()
    
    try:
        print("="*80)
        print("TESTING MANUAL TP CREATION")
        print("="*80)
        print("\nParameters:")
        print("  symbol: AKT_USDT")
        print("  side: BUY (original order side)")
        print("  tp_price: 1.5632")
        print("  quantity: 6.5")
        print("  entry_price: 1.5177")
        print("  source: manual")
        print("  dry_run: False (LIVE TRADING)")
        print("\n" + "="*80)
        print("Calling create_take_profit_order()...")
        print("="*80 + "\n")
        
        # Sanity check: Log before placing TP order to verify logging works
        logger.info("[TP_ORDER][TEST] Logging verification before placing TP order")
        print("✅ Test logger configured - check logs for [TP_ORDER][TEST]")
        
        result = create_take_profit_order(
            db=db,
            symbol="AKT_USDT",
            side="BUY",  # Original order side
            tp_price=1.5632,
            quantity=6.5,
            entry_price=1.5177,
            parent_order_id="test_parent_manual_123",
            oco_group_id=None,
            dry_run=False,  # LIVE TRADING - will send real request to exchange
            source="manual"
        )
        
        print("\n" + "="*80)
        print("RESULT")
        print("="*80)
        print(f"Result: {result}")
        
        if "error" in result:
            print(f"\n❌ Error: {result['error']}")
        else:
            order_id = result.get("order_id") or result.get("client_order_id")
            print(f"\n✅ Success! Order ID: {order_id}")
        
        print("\n" + "="*80)
        print("Check logs with:")
        print("  docker compose logs backend-aws 2>&1 | grep '\[TP_ORDER\]\[MANUAL\]' | tail -50")
        print("="*80)
        
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()
    
    return 0

if __name__ == '__main__':
    sys.exit(main())

