#!/usr/bin/env python3
"""
Verification checklist script for Crypto.com API key setup
Helps verify all requirements are met before testing authentication
"""
import os
import sys
from pathlib import Path

# Load credentials from .env.local if available
script_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.dirname(script_dir)
project_root = os.path.dirname(backend_dir)
env_file = Path(project_root) / '.env.local'

if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ[key] = value
    print("✅ Loaded credentials from .env.local")
else:
    print(f"⚠️  .env.local not found at {env_file}")

def clean_secret(value: str) -> str:
    """Clean secret from env (remove quotes, whitespace)"""
    v = (value or "").strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        v = v[1:-1].strip()
    return v

def preview_secret(value: str, left: int = 4, right: int = 4) -> str:
    """Preview secret safely"""
    v = value or ""
    if not v:
        return "<NOT_SET>"
    if len(v) <= left + right:
        return "<SET>"
    return f"{v[:left]}....{v[-right:]}"

def main():
    print("=" * 80)
    print("✅ CRYPTO.COM API KEY SETUP VERIFICATION CHECKLIST")
    print("=" * 80)
    print()
    
    checklist = []
    
    # 1. Environment Variables
    print("1️⃣  ENVIRONMENT VARIABLES")
    print("-" * 80)
    api_key = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_KEY", ""))
    api_secret = clean_secret(os.getenv("EXCHANGE_CUSTOM_API_SECRET", ""))
    
    if api_key:
        print(f"   ✅ EXCHANGE_CUSTOM_API_KEY: {preview_secret(api_key)}")
        checklist.append(("API Key configured", True))
    else:
        print(f"   ❌ EXCHANGE_CUSTOM_API_KEY: NOT SET")
        checklist.append(("API Key configured", False))
    
    if api_secret:
        print(f"   ✅ EXCHANGE_CUSTOM_API_SECRET: {preview_secret(api_secret)}")
        checklist.append(("API Secret configured", True))
    else:
        print(f"   ❌ EXCHANGE_CUSTOM_API_SECRET: NOT SET")
        checklist.append(("API Secret configured", False))
    
    # Check for common issues
    issues = []
    if api_key and (api_key.startswith("'") or api_key.startswith('"')):
        issues.append("API key has quotes - remove them")
    if api_secret and (api_secret.startswith("'") or api_secret.startswith('"')):
        issues.append("API secret has quotes - remove them")
    if api_key and len(api_key) < 10:
        issues.append("API key seems too short (should be ~20+ chars)")
    if api_secret and len(api_secret) < 10:
        issues.append("API secret seems too short (should be ~30+ chars)")
    
    if issues:
        print("   ⚠️  Potential issues:")
        for issue in issues:
            print(f"      - {issue}")
            checklist.append((f"Credential format: {issue}", False))
    else:
        checklist.append(("Credential format OK", True))
    
    print()
    
    # 2. Manual Checklist
    print("2️⃣  MANUAL VERIFICATION CHECKLIST")
    print("-" * 80)
    print("   Please verify the following in Crypto.com Exchange:")
    print()
    
    manual_checks = [
        ("API Key exists in Crypto.com Exchange", 
         "Go to https://exchange.crypto.com/ → Settings → API Keys"),
        ("API Key has 'Read' permission enabled", 
         "Edit API key → Enable 'Read' permission → Save"),
        ("API Key status is 'Enabled' (not Disabled/Suspended)", 
         "Check status in API Keys page"),
        ("Server IP address is whitelisted", 
         "Edit API key → Add your server's outbound IP to whitelist"),
        ("No extra spaces in IP whitelist entry", 
         "Verify IP is entered exactly, no leading/trailing spaces"),
    ]
    
    for i, (check, instruction) in enumerate(manual_checks, 1):
        print(f"   {i}. {check}")
        print(f"      💡 {instruction}")
        print()
        checklist.append((check, None))  # None = manual check
    
    # 3. Configuration Summary
    print("3️⃣  CONFIGURATION SUMMARY")
    print("-" * 80)
    use_proxy = os.getenv("USE_CRYPTO_PROXY", "false").lower() == "true"
    live_trading = os.getenv("LIVE_TRADING", "false").lower() == "true"
    
    print(f"   USE_CRYPTO_PROXY: {use_proxy}")
    print(f"   LIVE_TRADING: {live_trading}")
    print()
    
    if use_proxy:
        proxy_url = os.getenv("CRYPTO_PROXY_URL", "")
        print(f"   Proxy URL: {proxy_url if proxy_url else 'Not set'}")
        checklist.append(("Using proxy", True))
    else:
        base_url = os.getenv("EXCHANGE_CUSTOM_BASE_URL", "https://api.crypto.com/exchange/v1")
        print(f"   Base URL: {base_url}")
        checklist.append(("Direct connection", True))
    print()
    
    # 4. Next Steps
    print("4️⃣  NEXT STEPS")
    print("-" * 80)
    
    all_configured = all(item[1] for item in checklist if item[1] is not None)
    
    if all_configured:
        print("   ✅ All automatic checks passed!")
        print()
        print("   Now verify the manual checklist items above, then:")
        print("   1. Run diagnostic: python scripts/diagnose_auth_40101.py")
        print("   2. Test connection: python scripts/test_crypto_connection.py")
    else:
        print("   ⚠️  Some automatic checks failed:")
        for check, status in checklist:
            if status is False:
                print(f"      ❌ {check}")
        print()
        print("   Fix the issues above, then:")
        print("   1. Run diagnostic: python scripts/diagnose_auth_40101.py")
        print("   2. Test connection: python scripts/test_crypto_connection.py")
    
    print()
    print("=" * 80)
    
    # Return exit code
    return 0 if all_configured else 1

if __name__ == "__main__":
    sys.exit(main())

