#!/usr/bin/env python3
"""
Comprehensive diagnostic script for Crypto.com Exchange authentication issues.
This script helps identify and fix authentication failures.
"""
import sys
import os
import requests
from pathlib import Path
from typing import Dict, List, Tuple

# Load credentials from .env files BEFORE importing anything
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)

# Load from .env.local first, then .env.aws
env_files = ['.env.local', '.env.aws', '.env']
for env_file_name in env_files:
    env_file = Path(project_root) / env_file_name
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    # Don't override if already set
                    if key not in os.environ:
                        os.environ[key] = value
        print(f"✅ Loaded credentials from {env_file_name}")

# Set LIVE_TRADING before importing
os.environ['LIVE_TRADING'] = 'true'
sys.path.insert(0, backend_dir)

from app.services.brokers.crypto_com_trade import CryptoComTradeClient

def get_public_ip() -> str:
    """Get the public IP address"""
    try:
        response = requests.get('https://api.ipify.org', timeout=5)
        return response.text.strip()
    except Exception as e:
        return f"Error: {e}"

def check_credentials() -> Tuple[bool, List[str]]:
    """Check if credentials are configured"""
    issues = []
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
    
    if not api_key:
        issues.append("❌ EXCHANGE_CUSTOM_API_KEY is not set or empty")
    elif len(api_key) < 10:
        issues.append(f"⚠️  EXCHANGE_CUSTOM_API_KEY seems too short ({len(api_key)} chars)")
    
    if not api_secret:
        issues.append("❌ EXCHANGE_CUSTOM_API_SECRET is not set or empty")
    elif len(api_secret) < 10:
        issues.append(f"⚠️  EXCHANGE_CUSTOM_API_SECRET seems too short ({len(api_secret)} chars)")
    
    # Check for common issues
    if api_key and api_secret:
        # Check for quotes
        if (api_key.startswith('"') and api_key.endswith('"')) or \
           (api_key.startswith("'") and api_key.endswith("'")):
            issues.append("⚠️  EXCHANGE_CUSTOM_API_KEY has quotes - they will be stripped automatically")
        if (api_secret.startswith('"') and api_secret.endswith('"')) or \
           (api_secret.startswith("'") and api_secret.endswith("'")):
            issues.append("⚠️  EXCHANGE_CUSTOM_API_SECRET has quotes - they will be stripped automatically")
    
    return len(issues) == 0, issues

def test_public_api() -> Tuple[bool, str]:
    """Test public API (no authentication needed)"""
    try:
        response = requests.get(
            'https://api.crypto.com/v2/public/get-ticker?instrument_name=BTC_USDT',
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            if 'result' in data and 'data' in data['result']:
                ticker = data['result']['data'][0]
                price = float(ticker.get("a", 0))
                return True, f"✅ Public API works! BTC_USDT: ${price:.2f}"
        return False, f"⚠️  Public API responded with status {response.status_code}"
    except Exception as e:
        return False, f"❌ Public API error: {e}"

def test_private_api(client: CryptoComTradeClient) -> Tuple[bool, str, Dict]:
    """Test private API (authentication required)"""
    try:
        result = client.get_account_summary()
        if result and 'accounts' in result:
            accounts = result['accounts']
            return True, f"✅ Private API works! Found {len(accounts)} account(s)", result
        elif result and 'error' in result:
            error_msg = result.get('error', 'Unknown error')
            return False, f"❌ Private API error: {error_msg}", result
        else:
            return False, f"⚠️  Private API responded but unexpected format", result or {}
    except RuntimeError as e:
        error_str = str(e)
        if "authentication" in error_str.lower() or "401" in error_str:
            return False, f"❌ Authentication failed: {error_str}", {}
        return False, f"❌ Runtime error: {error_str}", {}
    except Exception as e:
        return False, f"❌ Exception: {e}", {}

def diagnose_issue(client: CryptoComTradeClient, error_msg: str) -> List[str]:
    """Provide specific diagnosis based on error message"""
    recommendations = []
    error_upper = error_msg.upper()
    
    if "40101" in error_msg or "AUTHENTICATION FAILURE" in error_upper:
        recommendations.append("🔍 Issue: Authentication failure (40101)")
        recommendations.append("")
        recommendations.append("Possible causes:")
        recommendations.append("1. ❌ API Key or Secret is incorrect")
        recommendations.append("   → Verify credentials in Crypto.com Exchange → Settings → API Keys")
        recommendations.append("   → Regenerate API key if needed")
        recommendations.append("")
        recommendations.append("2. ❌ API Key doesn't have required permissions")
        recommendations.append("   → Check that API key has 'Read' permission (required)")
        recommendations.append("   → Check that API key has 'Trade' permission (for placing orders)")
        recommendations.append("")
        recommendations.append("3. ❌ API Key is disabled or suspended")
        recommendations.append("   → Check API key status in Crypto.com Exchange")
        recommendations.append("   → Enable the key if it's disabled")
        recommendations.append("")
        recommendations.append("4. ❌ IP address not whitelisted")
        recommendations.append("   → Get your current IP: curl https://api.ipify.org")
        recommendations.append("   → Add IP to whitelist in Crypto.com Exchange → API Keys → Edit")
    
    if "40103" in error_msg or "IP ILLEGAL" in error_upper:
        recommendations.append("🔍 Issue: IP not whitelisted (40103)")
        recommendations.append("")
        recommendations.append("Solution:")
        recommendations.append("1. Get your current public IP address")
        recommendations.append("2. Go to Crypto.com Exchange → Settings → API Keys")
        recommendations.append("3. Edit your API key")
        recommendations.append("4. Add your IP address to the whitelist")
        recommendations.append("5. Save and wait a few seconds for changes to propagate")
    
    if not recommendations:
        recommendations.append("🔍 General authentication issue")
        recommendations.append("")
        recommendations.append("Check:")
        recommendations.append("1. API credentials are correct")
        recommendations.append("2. IP address is whitelisted")
        recommendations.append("3. API key has required permissions")
        recommendations.append("4. API key is enabled")
    
    return recommendations

def main():
    print("\n" + "="*70)
    print("🔍 CRYPTO.COM EXCHANGE AUTHENTICATION DIAGNOSTIC")
    print("="*70 + "\n")
    
    # Step 1: Check environment
    print("📋 Step 1: Checking Environment Configuration")
    print("-" * 70)
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
    
    print(f"USE_CRYPTO_PROXY: {use_proxy}")
    print(f"LIVE_TRADING: {live_trading}")
    print(f"Base URL: {base_url}")
    
    if use_proxy:
        proxy_url = os.getenv("CRYPTO_PROXY_URL", "http://127.0.0.1:9000")
        print(f"Proxy URL: {proxy_url}")
        print("⚠️  Using proxy - authentication is handled by proxy server")
        print("   Make sure proxy is running and configured correctly")
    
    print()
    
    # Step 2: Check credentials
    print("🔑 Step 2: Checking API Credentials")
    print("-" * 70)
    creds_ok, cred_issues = check_credentials()
    
    api_key = os.getenv("EXCHANGE_CUSTOM_API_KEY", "").strip()
    api_secret = os.getenv("EXCHANGE_CUSTOM_API_SECRET", "").strip()
    
    if api_key:
        preview_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
        print(f"API Key: {preview_key} (length: {len(api_key)})")
    else:
        print("API Key: ❌ NOT SET")
    
    if api_secret:
        print(f"API Secret: {'*' * min(20, len(api_secret))} (length: {len(api_secret)})")
    else:
        print("API Secret: ❌ NOT SET")
    
    if cred_issues:
        print()
        for issue in cred_issues:
            print(f"  {issue}")
    
    if not creds_ok:
        print("\n❌ Credentials are not properly configured. Please fix this first.")
        return
    
    print("✅ Credentials are configured")
    print()
    
    # Step 3: Get public IP
    print("🌐 Step 3: Checking Public IP Address")
    print("-" * 70)
    public_ip = get_public_ip()
    print(f"Your public IP: {public_ip}")
    if not use_proxy:
        print("⚠️  IMPORTANT: This IP must be whitelisted in Crypto.com Exchange")
        print("   Go to: https://exchange.crypto.com/ → Settings → API Keys → Edit")
        print("   Add this IP to the whitelist if it's not already there")
    print()
    
    # Step 4: Test public API
    print("🌍 Step 4: Testing Public API (No Authentication)")
    print("-" * 70)
    public_ok, public_msg = test_public_api()
    print(public_msg)
    if not public_ok:
        print("❌ Cannot connect to Crypto.com API. Check your internet connection.")
        return
    print()
    
    # Step 5: Test private API
    print("🔐 Step 5: Testing Private API (Authentication Required)")
    print("-" * 70)
    client = CryptoComTradeClient()
    client.live_trading = True
    
    print(f"Client configuration:")
    print(f"  - Using proxy: {client.use_proxy}")
    print(f"  - Base URL: {client.base_url}")
    print(f"  - Live trading: {client.live_trading}")
    print()
    
    print("Attempting to get account summary...")
    private_ok, private_msg, result = test_private_api(client)
    print(private_msg)
    
    if not private_ok:
        print()
        print("="*70)
        print("❌ AUTHENTICATION FAILED")
        print("="*70)
        print()
        
        # Provide specific diagnosis
        recommendations = diagnose_issue(client, private_msg)
        for rec in recommendations:
            print(rec)
        
        print()
        print("="*70)
        print("📝 NEXT STEPS")
        print("="*70)
        print()
        print("1. Verify your API credentials in Crypto.com Exchange:")
        print("   https://exchange.crypto.com/ → Settings → API Keys")
        print()
        print("2. Check API key permissions:")
        print("   - Read: Required for getting balances")
        print("   - Trade: Required for placing orders")
        print()
        print("3. Verify IP whitelist:")
        print(f"   - Your current IP: {public_ip}")
        print("   - Add this IP to your API key whitelist")
        print()
        print("4. If using proxy, verify proxy is running and configured correctly")
        print()
        print("5. After fixing, restart the backend:")
        print("   docker compose restart backend-aws  # For AWS")
        print("   docker compose restart backend      # For local")
        print()
    else:
        print()
        print("="*70)
        print("✅ AUTHENTICATION SUCCESSFUL")
        print("="*70)
        print()
        if result and 'accounts' in result:
            print("Account balances:")
            for account in result['accounts'][:10]:
                currency = account.get('currency', '')
                balance = account.get('balance', '0')
                available = account.get('available', '0')
                print(f"  {currency}: {balance} (available: {available})")
        print()
        print("✅ Your Crypto.com Exchange connection is working correctly!")
        print()
    
    print("="*70 + "\n")

if __name__ == "__main__":
    main()

