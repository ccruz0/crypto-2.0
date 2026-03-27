#!/usr/bin/env python3
"""
Quick test to verify diagnostic scripts can run
Tests imports and basic functionality
"""
import sys
import os

print("=" * 60)
print("🧪 TESTING DIAGNOSTIC SCRIPTS SETUP")
print("=" * 60)

# Test 1: Python version
print("\n1️⃣  Python Version:")
print(f"   {sys.version}")

# Test 2: Required packages
print("\n2️⃣  Required Packages:")
required = ['requests', 'hmac', 'hashlib', 'json', 'time', 'pathlib', 'datetime']
missing = []
for pkg in required:
    try:
        if pkg == 'hmac':
            import hmac
        elif pkg == 'hashlib':
            import hashlib
        elif pkg == 'json':
            import json
        elif pkg == 'time':
            import time
        elif pkg == 'pathlib':
            from pathlib import Path
        elif pkg == 'datetime':
            from datetime import datetime
        elif pkg == 'requests':
            import requests
        print(f"   ✅ {pkg}")
    except ImportError:
        print(f"   ❌ {pkg} - MISSING")
        missing.append(pkg)

if missing:
    print(f"\n   ⚠️  Missing packages: {', '.join(missing)}")
    print(f"   Install with: pip3 install {' '.join(missing)}")
else:
    print(f"\n   ✅ All required packages available")

# Test 3: Find backend directory
print("\n3️⃣  Backend Directory:")
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
print(f"   Script dir: {script_dir}")
print(f"   Backend dir: {backend_dir}")

# Test 4: Check if crypto_com_trade exists
print("\n4️⃣  Backend Code:")
crypto_trade_path = os.path.join(backend_dir, 'app', 'services', 'brokers', 'crypto_com_trade.py')
if os.path.exists(crypto_trade_path):
    print(f"   ✅ Found: {crypto_trade_path}")
else:
    print(f"   ❌ Not found: {crypto_trade_path}")

# Test 5: Environment variables
print("\n5️⃣  Environment Variables:")
api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "")
api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "")

if api_key:
    print(f"   ✅ EXCHANGE_CUSTOM_API_KEY: {api_key[:4]}....{api_key[-4:] if len(api_key) > 8 else ''} (len: {len(api_key)})")
else:
    print(f"   ❌ EXCHANGE_CUSTOM_API_KEY: NOT SET")

if api_secret:
    print(f"   ✅ EXCHANGE_CUSTOM_API_SECRET: SET (len: {len(api_secret)})")
else:
    print(f"   ❌ EXCHANGE_CUSTOM_API_SECRET: NOT SET")

# Test 6: .env file locations
print("\n6️⃣  .env File Search:")
from pathlib import Path
env_files = [
    Path(backend_dir).parent / '.env.local',
    Path(backend_dir).parent / '.env',
    Path.home() / '.env.local',
    Path('/opt/automated-trading-platform/.env.local'),
    Path('/home/ubuntu/crypto-2.0/.env.local'),
]

found = False
for env_path in env_files:
    if env_path.exists():
        print(f"   ✅ Found: {env_path}")
        found = True
        break

if not found:
    print(f"   ⚠️  No .env file found in common locations")
    print(f"   Searched:")
    for env_path in env_files:
        print(f"      - {env_path}")

# Test 7: Network connectivity
print("\n7️⃣  Network Connectivity:")
try:
    import requests
    response = requests.get("https://api.ipify.org", timeout=5)
    if response.status_code == 200:
        ip = response.text.strip()
        print(f"   ✅ Outbound IP: {ip}")
    else:
        print(f"   ⚠️  Could not get IP (status: {response.status_code})")
except Exception as e:
    print(f"   ❌ Network error: {e}")

# Summary
print("\n" + "=" * 60)
print("📋 SUMMARY")
print("=" * 60)

all_good = True
if missing:
    print("❌ Missing required packages")
    all_good = False
if not os.path.exists(crypto_trade_path):
    print("❌ Backend code not found")
    all_good = False
if not api_key or not api_secret:
    print("⚠️  API credentials not set (will try to load from .env)")
if not found and not (api_key and api_secret):
    print("⚠️  No .env file found and credentials not in environment")

if all_good:
    print("✅ All checks passed! Diagnostic scripts should work.")
    print("\n💡 Next step: Run diagnostic script")
    print("   python3 scripts/deep_auth_diagnostic.py")
else:
    print("⚠️  Some issues found. Fix them before running diagnostics.")
    sys.exit(1)

print("=" * 60)

