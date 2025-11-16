#!/usr/bin/env python3
"""
Script to capture and compare TP order payloads by monkey-patching the HTTP request.
This captures the actual payloads sent to the exchange without relying on logs.
"""
import sys
import os
import json
sys.path.insert(0, '/app')

from unittest.mock import patch
from app.database import SessionLocal
from app.services.tp_sl_order_creator import create_take_profit_order

# Global storage for captured payloads
captured_payloads = []

def capture_http_post(*args, **kwargs):
    """Capture HTTP POST requests and store payloads"""
    global captured_payloads
    if 'json' in kwargs:
        payload = kwargs['json']
        captured_payloads.append({
            'url': args[0] if args else kwargs.get('url', 'unknown'),
            'payload': payload,
            'source': 'manual'  # We'll set this based on context
        })
        print(f"\n{'='*80}")
        print(f"CAPTURED PAYLOAD #{len(captured_payloads)}")
        print(f"{'='*80}")
        print(f"URL: {args[0] if args else kwargs.get('url', 'unknown')}")
        print(f"Payload JSON:")
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        print(f"{'='*80}\n")
    
    # Call the real requests.post (we'll need to import it)
    import requests
    return requests.post(*args, **kwargs)

def main():
    """Test manual TP creation and capture payloads"""
    db = SessionLocal()
    
    try:
        print("="*80)
        print("CAPTURING MANUAL TP PAYLOADS")
        print("="*80)
        
        # Monkey-patch requests.post to capture payloads
        import requests
        original_post = requests.post
        
        def patched_post(*args, **kwargs):
            if 'json' in kwargs:
                payload = kwargs['json']
                # Extract params from the signed payload
                params = payload.get('params', {})
                print(f"\n{'='*80}")
                print(f"CAPTURED PAYLOAD")
                print(f"{'='*80}")
                print(f"URL: {args[0] if args else 'unknown'}")
                print(f"Method: {payload.get('method', 'unknown')}")
                print(f"Params:")
                print(json.dumps(params, indent=2, ensure_ascii=False))
                print(f"{'='*80}\n")
                captured_payloads.append({
                    'url': args[0] if args else 'unknown',
                    'method': payload.get('method'),
                    'params': params
                })
            return original_post(*args, **kwargs)
        
        requests.post = patched_post
        
        print("\nCalling create_take_profit_order()...")
        result = create_take_profit_order(
            db=db,
            symbol="AKT_USDT",
            side="BUY",
            tp_price=1.5632,
            quantity=6.5,
            entry_price=1.5177,
            parent_order_id="test_capture_manual",
            oco_group_id=None,
            dry_run=False,
            source="manual"
        )
        
        print(f"\nResult: {result}")
        print(f"\nCaptured {len(captured_payloads)} payload(s)")
        
        # Restore original
        requests.post = original_post
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Exception: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

