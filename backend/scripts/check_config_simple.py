#!/usr/bin/env python3
"""
Simple script to check LIVE_TRADING and API credentials from environment variables
(Works without database connection)
"""

import os
import sys

def check_env_file():
    """Check .env files for configuration"""
    env_files = ['.env', '.env.local', '.env.aws']
    found_files = []
    
    for env_file in env_files:
        if os.path.exists(env_file):
            found_files.append(env_file)
    
    return found_files

def read_env_file(filepath):
    """Read environment variables from a file"""
    env_vars = {}
    try:
        with open(filepath, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    env_vars[key.strip()] = value.strip().strip('"').strip("'")
    except Exception as e:
        print(f"   ⚠️  Error reading {filepath}: {e}")
    return env_vars

def check_live_trading():
    """Check LIVE_TRADING from environment"""
    print("=" * 70)
    print("1. LIVE_TRADING STATUS")
    print("=" * 70)
    
    # Check environment variable
    env_value = os.getenv("LIVE_TRADING", "NOT_SET")
    env_bool = env_value.lower() == "true" if env_value != "NOT_SET" else None
    
    print(f"   🔧 Environment Variable: {env_value}")
    if env_bool is not None:
        status_emoji = "✅" if env_bool else "❌"
        print(f"   {status_emoji} Status: {env_bool}")
    
    # Check .env files
    env_files = check_env_file()
    if env_files:
        print()
        print("   📄 Checking .env files:")
        for env_file in env_files:
            env_vars = read_env_file(env_file)
            live_trading = env_vars.get("LIVE_TRADING", "NOT_SET")
            print(f"      {env_file}: LIVE_TRADING={live_trading}")
            if live_trading.lower() == "true":
                print(f"         ✅ LIVE_TRADING is ENABLED in {env_file}")
            elif live_trading.lower() == "false":
                print(f"         ❌ LIVE_TRADING is DISABLED in {env_file}")
    else:
        print("   ⚠️  No .env files found")
    
    # Final determination
    final_status = env_bool if env_bool is not None else False
    if not final_status:
        print()
        print("   ⚠️  WARNING: LIVE_TRADING appears to be DISABLED")
        print("   ⚠️  All orders will be in DRY_RUN mode (simulated)")
    
    return final_status

def check_api_credentials():
    """Check API credentials"""
    print()
    print("=" * 70)
    print("2. API CREDENTIALS")
    print("=" * 70)
    
    # Check environment variables
    api_key = os.getenv("CRYPTO_COM_API_KEY")
    api_secret = os.getenv("CRYPTO_COM_API_SECRET")
    base_url = os.getenv("CRYPTO_COM_BASE_URL", "https://api.crypto.com/exchange/v1")
    
    print(f"   🔑 API Key: {'✅ SET' if api_key else '❌ NOT SET'}")
    if api_key:
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        print(f"      Value: {masked_key}")
    
    print(f"   🔐 API Secret: {'✅ SET' if api_secret else '❌ NOT SET'}")
    if api_secret:
        masked_secret = f"{api_secret[:8]}...{api_secret[-4:]}" if len(api_secret) > 12 else "***"
        print(f"      Value: {masked_secret}")
    
    print(f"   🌐 Base URL: {base_url}")
    
    # Check if test/sandbox
    is_test = "sandbox" in base_url.lower() or "test" in base_url.lower()
    if is_test:
        print("   ⚠️  WARNING: Using TEST/SANDBOX environment!")
    
    # Check .env files
    env_files = check_env_file()
    if env_files:
        print()
        print("   📄 Checking .env files:")
        for env_file in env_files:
            env_vars = read_env_file(env_file)
            file_api_key = env_vars.get("CRYPTO_COM_API_KEY", "NOT_SET")
            file_api_secret = env_vars.get("CRYPTO_COM_API_SECRET", "NOT_SET")
            file_base_url = env_vars.get("CRYPTO_COM_BASE_URL", "NOT_SET")
            
            print(f"      {env_file}:")
            if file_api_key != "NOT_SET":
                masked = f"{file_api_key[:8]}...{file_api_key[-4:]}" if len(file_api_key) > 12 else "***"
                print(f"         API_KEY: {masked} {'✅' if file_api_key else '❌'}")
            else:
                print(f"         API_KEY: NOT_SET ❌")
            
            if file_api_secret != "NOT_SET":
                masked = f"{file_api_secret[:8]}...{file_api_secret[-4:]}" if len(file_api_secret) > 12 else "***"
                print(f"         API_SECRET: {masked} {'✅' if file_api_secret else '❌'}")
            else:
                print(f"         API_SECRET: NOT_SET ❌")
            
            if file_base_url != "NOT_SET":
                print(f"         BASE_URL: {file_base_url}")
                if "sandbox" in file_base_url.lower() or "test" in file_base_url.lower():
                    print(f"            ⚠️  TEST/SANDBOX environment")
    
    return api_key, api_secret, base_url, is_test

def main():
    print()
    print("🔍 TRADING CONFIGURATION CHECK (Simple Version)")
    print()
    
    # 1. Check LIVE_TRADING
    live_trading = check_live_trading()
    
    # 2. Check API credentials
    api_key, api_secret, base_url, is_test = check_api_credentials()
    
    # Summary
    print()
    print("=" * 70)
    print("📋 SUMMARY")
    print("=" * 70)
    
    issues = []
    warnings = []
    
    if not live_trading:
        issues.append("❌ LIVE_TRADING is DISABLED - all orders are simulated")
    
    if not api_key or not api_secret:
        issues.append("❌ API credentials are missing")
    
    if is_test:
        warnings.append("⚠️  Using TEST/SANDBOX environment")
    
    if issues:
        print()
        print("🚨 CRITICAL ISSUES:")
        for issue in issues:
            print(f"   {issue}")
    
    if warnings:
        print()
        print("⚠️  WARNINGS:")
        for warning in warnings:
            print(f"   {warning}")
    
    if not issues and not warnings:
        print()
        print("✅ Configuration looks good!")
        print("   - LIVE_TRADING is enabled")
        print("   - API credentials are set")
        print("   - Using production environment")
    
    # Recommendations
    print()
    print("=" * 70)
    print("💡 RECOMMENDATIONS")
    print("=" * 70)
    
    if not live_trading:
        print()
        print("To enable LIVE_TRADING:")
        print("   1. Add to .env file:")
        print("      LIVE_TRADING=true")
        print()
        print("   2. Or set environment variable:")
        print("      export LIVE_TRADING=true")
        print()
        print("   3. Or update database (if accessible):")
        print("      UPDATE trading_settings SET setting_value='true' WHERE setting_key='LIVE_TRADING';")
    
    if not api_key or not api_secret:
        print()
        print("To set API credentials:")
        print("   1. Get API key from Crypto.com Exchange:")
        print("      https://exchange.crypto.com/exchange/settings/api-management")
        print()
        print("   2. Add to .env file:")
        print("      CRYPTO_COM_API_KEY=your_key_here")
        print("      CRYPTO_COM_API_SECRET=your_secret_here")
        print()
        print("   3. Or set environment variables:")
        print("      export CRYPTO_COM_API_KEY='your_key'")
        print("      export CRYPTO_COM_API_SECRET='your_secret'")
    
    if is_test:
        print()
        print("⚠️  You're using a TEST/SANDBOX environment")
        print("   - Switch to production URL in .env:")
        print("     CRYPTO_COM_BASE_URL=https://api.crypto.com/exchange/v1")
    
    print()
    print("=" * 70)
    print()
    print("💡 ABOUT THE ORDERS YOU'RE SEEING:")
    print()
    if not live_trading:
        print("   ❌ The orders in Telegram are LIKELY SIMULATED")
        print("   ❌ They were created in DRY_RUN mode")
        print("   ❌ They were never sent to the actual exchange")
        print("   ❌ That's why you don't see them in your Crypto.com account")
    else:
        print("   ✅ LIVE_TRADING is enabled")
        print("   ⚠️  But verify:")
        print("      - Are the API credentials correct?")
        print("      - Do they match the account you're checking?")
        print("      - Are you checking the right exchange (Exchange vs App)?")
    print()

if __name__ == "__main__":
    main()






