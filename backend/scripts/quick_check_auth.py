#!/usr/bin/env python3
"""
Quick diagnostic script for Crypto.com API authentication error 40101
Provides fast checks and actionable recommendations
"""
import os
import sys
import requests
from pathlib import Path

# Load .env.local if available
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)

env_files = [
    Path(project_root) / '.env.local',
    Path(project_root) / '.env',
    Path('/opt/automated-trading-platform/.env.local'),
    Path('/home/ubuntu/crypto-2.0/.env.local'),
]

for env_path in env_files:
    if env_path.exists():
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key not in os.environ:
                        os.environ[key] = value
        print(f"✅ Loaded from {env_path}\n")
        break

def clean_secret(value: str) -> str:
    """Clean secret from env"""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v

def preview_secret(value: str) -> str:
    """Preview secret safely"""
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= 8:
        return "<SET>"
    return f"{v[:4]}....{v[-4:]}"

def main():
    print("=" * 70)
    print("🔍 QUICK AUTH CHECK - Error 40101 Diagnostic")
    print("=" * 70)
    print()
    
    # 1. Check credentials
    print("1️⃣  CREDENTIALS CHECK")
    print("-" * 70)
    api_key = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    
    print(f"   API Key: {preview_secret(api_key)} (length: {len(api_key)})")
    print(f"   API Secret: {preview_secret(api_secret)} (length: {len(api_secret)})")
    
    if not api_key or not api_secret:
        print("\n   ❌ CRITICAL: Credentials not configured!")
        print("\n   💡 SOLUTION:")
        print("   1. Set EXCHANGE_CUSTOM_API_KEY and EXCHANGE_CUSTOM_API_SECRET")
        print("   2. In AWS: Check .env.local file or environment variables")
        print("   3. Restart backend: docker compose restart backend")
        return False
    
    # Check for common issues
    issues = []
    if api_key.startswith("'") or api_key.startswith('"'):
        issues.append("API key has quotes - remove them")
    if api_secret.startswith("'") or api_secret.startswith('"'):
        issues.append("API secret has quotes - remove them")
    if len(api_key) < 10:
        issues.append("API key seems too short (should be ~20+ chars)")
    if len(api_secret) < 20:
        issues.append("API secret seems too short (should be ~30+ chars)")
    
    if issues:
        print(f"\n   ⚠️  Issues found:")
        for issue in issues:
            print(f"      • {issue}")
    else:
        print("   ✅ Credentials format looks OK")
    
    # 2. Check configuration
    print("\n2️⃣  CONFIGURATION CHECK")
    print("-" * 70)
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    
    print(f"   USE_CRYPTO_PROXY: {use_proxy}")
    print(f"   LIVE_TRADING: {live_trading}")
    
    if not live_trading:
        print("   ⚠️  LIVE_TRADING is false - API calls may be simulated")
    
    # 3. Test API connection
    print("\n3️⃣  API CONNECTION TEST")
    print("-" * 70)
    
    try:
        # Get outbound IP
        try:
            egress_ip = requests.get("https://api.ipify.org", timeout=3).text.strip()
            print(f"   Outbound IP: {egress_ip}")
            print(f"   💡 Make sure this IP is whitelisted in Crypto.com Exchange")
        except:
            print("   ⚠️  Could not determine outbound IP")
        
        # Try to import and test the trade client
        sys.path.insert(0, backend_dir)
        try:
            from app.services.brokers.crypto_com_trade import trade_client
            
            print("\n   Testing API call...")
            result = trade_client.get_account_summary()
            
            if result and "accounts" in result:
                print("   ✅ SUCCESS! API authentication working")
                print(f"   Found {len(result.get('accounts', []))} account(s)")
                return True
            else:
                print("   ⚠️  API call succeeded but unexpected response format")
                return False
                
        except RuntimeError as e:
            error_msg = str(e)
            if "40101" in error_msg:
                print("   ❌ ERROR 40101: Authentication failure")
                print("\n   🔧 ACTION REQUIRED:")
                print("   1. Verify API key/secret match Crypto.com Exchange exactly")
                print("   2. Check API key has 'Read' permission enabled")
                print("   3. Verify API key is not disabled/suspended")
                print("   4. Check IP whitelist includes your server IP")
                print("\n   📋 Steps to fix:")
                print("   • Go to https://exchange.crypto.com/")
                print("   • Settings → API Keys")
                print("   • Edit your API key")
                print("   • Enable 'Read' permission")
                print("   • Add IP to whitelist if required")
                print("   • Verify API key is 'Active' (not Disabled/Suspended)")
                return False
            elif "40103" in error_msg:
                print("   ❌ ERROR 40103: IP not whitelisted")
                print(f"\n   🔧 Add IP {egress_ip} to Crypto.com Exchange API key whitelist")
                return False
            else:
                print(f"   ❌ Error: {error_msg[:200]}")
                return False
                
        except Exception as e:
            print(f"   ❌ Unexpected error: {str(e)[:200]}")
            return False
            
    except Exception as e:
        print(f"   ❌ Could not test connection: {str(e)[:200]}")
        return False

if __name__ == "__main__":
    success = main()
    print("\n" + "=" * 70)
    if success:
        print("✅ All checks passed!")
    else:
        print("❌ Issues found - see recommendations above")
    print("=" * 70)
    sys.exit(0 if success else 1)
















