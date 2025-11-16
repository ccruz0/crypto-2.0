#!/usr/bin/env python3

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.routes_signals_fixed import get_signals

if __name__ == "__main__":
    print("Testing signals endpoint directly...")
    
    try:
        # Test the get_signals function directly
        result = get_signals(exchange="CRYPTO_COM", symbol="DOGE_USDT")
        print(f"DOGE_USDT price from signals: ${result['price']}")
        print(f"Success: {result['signals']['buy'] is not None}")
        print(f"Method: {result['method']}")
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

