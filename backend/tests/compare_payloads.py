#!/usr/bin/env python3
"""
Script to compare payloads between automatic and manual TP/SL creation flows.
This ensures both flows send identical parameters to the exchange API.
"""
import sys
import os
sys.path.insert(0, '/app')

from unittest.mock import patch, MagicMock
from app.database import SessionLocal
from app.services.tp_sl_order_creator import create_take_profit_order

# Global variables to capture arguments
captured_auto = {}
captured_manual = {}

def make_capture_function(capture_dict, call_id):
    """Create a capture function that returns a dict"""
    def capture_func(*args, **kwargs):
        """Capture kwargs from call"""
        captured = {}
        if args:
            param_names = ['symbol', 'side', 'price', 'qty']
            for i, arg in enumerate(args[1:]):  # Skip 'self'
                if i < len(param_names):
                    captured[param_names[i]] = arg
        captured.update(kwargs)
        capture_dict.update(captured)
        # Return a mock successful response (must be a dict, not an object)
        return {
            "order_id": f"test_order_{call_id}",
            "client_order_id": f"test_order_{call_id}",
            "status": "OPEN"
        }
    return capture_func

def main():
    """Compare automatic vs manual TP creation payloads"""
    db = SessionLocal()
    
    try:
        # Test parameters (same for both flows)
        symbol = "AKT_USDT"
        original_side = "BUY"  # Original order side
        tp_price = 1.5632
        quantity = 6.5
        entry_price = 1.5177
        
        print("="*80)
        print("COMPARING AUTO vs MANUAL TP CREATION PAYLOADS")
        print("="*80)
        
        # Mock trade_client
        with patch('app.services.tp_sl_order_creator.trade_client') as mock_trade_client:
            call_count = [0]  # Use list to allow modification in nested function
            
            def mock_place_tp(*args, **kwargs):
                call_count[0] += 1
                if call_count[0] == 1:
                    # First call (auto)
                    return make_capture_function(captured_auto, "auto")(*args, **kwargs)
                else:
                    # Second call (manual)
                    return make_capture_function(captured_manual, "manual")(*args, **kwargs)
            
            mock_trade_client.place_take_profit_order = mock_place_tp
            
            # FLOW 1: Automatic (as called from exchange_sync.py)
            print("\n[FLOW 1] Automatic TP creation (exchange_sync.py style)...")
            captured_auto.clear()
            auto_result = create_take_profit_order(
                db=db,
                symbol=symbol,
                side=original_side,  # "BUY" - original order side
                tp_price=tp_price,
                quantity=quantity,
                entry_price=entry_price,
                parent_order_id="parent_auto_123",
                oco_group_id="oco_auto_123",
                dry_run=False,
                source="auto"
            )
            print(f"  ✅ Auto flow completed")
            
            # FLOW 2: Manual (as called from sl_tp_checker.py)
            print("\n[FLOW 2] Manual TP creation (sl_tp_checker.py style)...")
            captured_manual.clear()
            manual_result = create_take_profit_order(
                db=db,
                symbol=symbol,
                side=original_side,  # "BUY" - original order side (same as auto)
                tp_price=tp_price,
                quantity=quantity,
                entry_price=entry_price,
                parent_order_id="parent_manual_456",
                oco_group_id="oco_manual_456",
                dry_run=False,
                source="manual"
            )
            print(f"  ✅ Manual flow completed")
        
        # Compare payloads
        print("\n" + "="*80)
        print("PAYLOAD COMPARISON")
        print("="*80)
        
        # Fields that can differ (not sent to exchange):
        exclude_fields = {'source'}  # source is only for logging
        
        auto_params = {k: v for k, v in captured_auto.items() if k not in exclude_fields}
        manual_params = {k: v for k, v in captured_manual.items() if k not in exclude_fields}
        
        print(f"\nAUTO payload:")
        for k, v in sorted(auto_params.items()):
            print(f"  {k}: {repr(v)}")
        
        print(f"\nMANUAL payload:")
        for k, v in sorted(manual_params.items()):
            print(f"  {k}: {repr(v)}")
        
        print("\n" + "="*80)
        print("FIELD-BY-FIELD COMPARISON")
        print("="*80)
        
        all_keys = set(auto_params.keys()) | set(manual_params.keys())
        differences = []
        matches = []
        
        for key in sorted(all_keys):
            auto_val = auto_params.get(key)
            manual_val = manual_params.get(key)
            if auto_val == manual_val:
                matches.append(key)
                print(f"  ✅ {key}: {repr(auto_val)} (MATCH)")
            else:
                differences.append(key)
                print(f"  ❌ {key}:")
                print(f"      AUTO:   {repr(auto_val)}")
                print(f"      MANUAL: {repr(manual_val)}")
        
        print("\n" + "="*80)
        print("SUMMARY")
        print("="*80)
        print(f"  Matches: {len(matches)}")
        print(f"  Differences: {len(differences)}")
        
        if differences:
            print(f"\n  ❌ PAYLOADS DIFFER! Fields that differ: {differences}")
            print("\n  These differences must be fixed to ensure both flows work identically.")
            return 1
        else:
            print(f"\n  ✅ PAYLOADS MATCH! Both flows send identical parameters to the exchange.")
            return 0
            
    except Exception as e:
        print(f"\n❌ Error during comparison: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

