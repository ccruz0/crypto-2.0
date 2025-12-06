#!/usr/bin/env python3
"""Direct diagnostic script for Crypto.com authentication - runs inside backend container"""
import sys
import os
import json
sys.path.insert(0, '/app')

import logging
from app.services.brokers.crypto_com_trade import CryptoComTradeClient

logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')
logger = logging.getLogger(__name__)

print("=" * 80)
print("CRYPTO.COM AUTHENTICATION DIAGNOSTIC")
print("=" * 80)
print()

try:
    client = CryptoComTradeClient()
    print("✅ CryptoComTradeClient initialized")
    print()
    
    print("Attempting to get account summary...")
    print()
    
    result = client.get_account_summary()
    
    if result and "accounts" in result:
        print(f"✅ SUCCESS: Got {len(result.get('accounts', []))} accounts")
        print(json.dumps(result, indent=2)[:500])
    else:
        print(f"❌ FAILED: {result}")
        
except Exception as e:
    print(f"❌ ERROR: {e}")
    import traceback
    traceback.print_exc()

