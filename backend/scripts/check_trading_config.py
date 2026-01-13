#!/usr/bin/env python3
"""
Comprehensive script to check:
1. LIVE_TRADING status (database and environment)
2. API credentials configuration
3. Connection to Crypto.com Exchange
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from app.database import SessionLocal
from app.models.trading_settings import TradingSettings
from app.utils.live_trading import get_live_trading_status
from app.services.brokers.crypto_com_trade import trade_client
import json

def check_live_trading():
    """Check LIVE_TRADING status from multiple sources"""
    print("=" * 70)
    print("1. LIVE_TRADING STATUS CHECK")
    print("=" * 70)
    
    # Check database
    db = SessionLocal()
    try:
        setting = db.query(TradingSettings).filter(
            TradingSettings.setting_key == "LIVE_TRADING"
        ).first()
        
        db_value = None
        if setting:
            db_value = setting.setting_value.lower() == "true"
            print(f"   📊 Database: {setting.setting_value} → {db_value}")
        else:
            print("   📊 Database: No setting found")
        
        # Check environment variable
        env_value = os.getenv("LIVE_TRADING", "NOT_SET")
        env_bool = env_value.lower() == "true" if env_value != "NOT_SET" else None
        print(f"   🔧 Environment: {env_value} → {env_bool}")
        
        # Get final status (what the system actually uses)
        final_status = get_live_trading_status(db)
        status_emoji = "✅" if final_status else "❌"
        print(f"   {status_emoji} FINAL STATUS: {final_status}")
        
        if not final_status:
            print()
            print("   ⚠️  WARNING: LIVE_TRADING is DISABLED!")
            print("   ⚠️  All orders will be in DRY_RUN mode (simulated)")
            print("   ⚠️  No real trades will be executed on the exchange")
        
        return final_status, db_value, env_value
    finally:
        db.close()

def check_api_credentials():
    """Check API credentials configuration"""
    print()
    print("=" * 70)
    print("2. API CREDENTIALS CHECK")
    print("=" * 70)
    
    # Check environment variables
    api_key = os.getenv("CRYPTO_COM_API_KEY")
    api_secret = os.getenv("CRYPTO_COM_API_SECRET")
    base_url = os.getenv("CRYPTO_COM_BASE_URL", "https://api.crypto.com/exchange/v1")
    
    # Check if credentials are set
    api_key_set = "✅ SET" if api_key else "❌ NOT SET"
    api_secret_set = "✅ SET" if api_secret else "❌ NOT SET"
    
    print(f"   🔑 API Key: {api_key_set}")
    if api_key:
        # Show first 8 and last 4 characters for security
        masked_key = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else "***"
        print(f"      Value: {masked_key}")
    
    print(f"   🔐 API Secret: {api_secret_set}")
    if api_secret:
        masked_secret = f"{api_secret[:8]}...{api_secret[-4:]}" if len(api_secret) > 12 else "***"
        print(f"      Value: {masked_secret}")
    
    print(f"   🌐 Base URL: {base_url}")
    
    # Check if it's test/sandbox
    is_test = "sandbox" in base_url.lower() or "test" in base_url.lower()
    if is_test:
        print("   ⚠️  WARNING: Using TEST/SANDBOX environment!")
        print("   ⚠️  Orders will be simulated, not real trades")
    
    # Check trade client configuration
    print()
    print("   📋 Trade Client Configuration:")
    print(f"      live_trading: {getattr(trade_client, 'live_trading', 'NOT_SET')}")
    print(f"      base_url: {getattr(trade_client, 'base_url', 'NOT_SET')}")
    print(f"      use_proxy: {getattr(trade_client, 'use_proxy', 'NOT_SET')}")
    
    return api_key, api_secret, base_url, is_test

def test_connection():
    """Test connection to Crypto.com Exchange"""
    print()
    print("=" * 70)
    print("3. CONNECTION TEST")
    print("=" * 70)
    
    try:
        print("   🔄 Testing connection to Crypto.com Exchange...")
        
        # Try to get account summary (requires valid credentials)
        result = trade_client.get_account_summary()
        
        if result and "accounts" in result:
            accounts = result["accounts"]
            print(f"   ✅ Connection successful!")
            print(f"   📊 Found {len(accounts)} account(s)")
            
            # Show balances (first 5)
            print()
            print("   💰 Account Balances:")
            for account in accounts[:5]:
                currency = account.get("currency", "N/A")
                balance = account.get("balance", "0")
                available = account.get("available", "0")
                print(f"      {currency}: {balance} (available: {available})")
            
            if len(accounts) > 5:
                print(f"      ... and {len(accounts) - 5} more")
            
            return True, result
        else:
            print("   ⚠️  Connection returned unexpected format")
            print(f"   Response: {json.dumps(result, indent=2)[:200]}...")
            return False, result
            
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        print()
        print("   💡 Possible causes:")
        print("      - Invalid API credentials")
        print("      - Network connectivity issues")
        print("      - API key doesn't have required permissions")
        print("      - Using wrong API endpoint (sandbox vs production)")
        return False, None

def test_order_history():
    """Test fetching order history"""
    print()
    print("=" * 70)
    print("4. ORDER HISTORY TEST")
    print("=" * 70)
    
    try:
        print("   🔄 Fetching recent order history...")
        result = trade_client.get_order_history(page_size=10, page=0)
        
        if result and "data" in result:
            data = result["data"]
            order_list = data.get("order_list", [])
            print(f"   ✅ Successfully fetched order history")
            print(f"   📋 Found {len(order_list)} recent order(s)")
            
            if order_list:
                print()
                print("   📊 Recent Orders:")
                for order in order_list[:5]:
                    order_id = order.get("order_id", "N/A")
                    symbol = order.get("instrument_name", "N/A")
                    side = order.get("side", "N/A")
                    status = order.get("status", "N/A")
                    order_type = order.get("type", "N/A")
                    print(f"      {order_id[:20]}... | {symbol} | {side} | {status} | {order_type}")
            
            return True, order_list
        else:
            print("   ⚠️  Order history returned unexpected format")
            return False, None
            
    except Exception as e:
        print(f"   ❌ Failed to fetch order history: {e}")
        return False, None

def main():
    print()
    print("🔍 COMPREHENSIVE TRADING CONFIGURATION CHECK")
    print()
    
    # 1. Check LIVE_TRADING
    live_trading, db_value, env_value = check_live_trading()
    
    # 2. Check API credentials
    api_key, api_secret, base_url, is_test = check_api_credentials()
    
    # 3. Test connection
    connection_ok, account_data = test_connection()
    
    # 4. Test order history
    history_ok, orders = test_order_history()
    
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
    
    if not connection_ok:
        issues.append("❌ Cannot connect to Crypto.com Exchange")
    
    if not history_ok:
        warnings.append("⚠️  Cannot fetch order history")
    
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
        print("✅ All checks passed! System is configured for live trading.")
    
    # Recommendations
    print()
    print("=" * 70)
    print("💡 RECOMMENDATIONS")
    print("=" * 70)
    
    if not live_trading:
        print()
        print("To enable LIVE_TRADING:")
        print("   1. Database method:")
        print("      UPDATE trading_settings SET setting_value='true' WHERE setting_key='LIVE_TRADING';")
        print()
        print("   2. Environment variable method:")
        print("      export LIVE_TRADING=true")
        print("      (or add to .env file)")
    
    if not api_key or not api_secret:
        print()
        print("To set API credentials:")
        print("   1. Get API key from Crypto.com Exchange:")
        print("      https://exchange.crypto.com/exchange/settings/api-management")
        print()
        print("   2. Set environment variables:")
        print("      export CRYPTO_COM_API_KEY='your_key'")
        print("      export CRYPTO_COM_API_SECRET='your_secret'")
        print("      (or add to .env file)")
    
    if is_test:
        print()
        print("⚠️  You're using a TEST/SANDBOX environment")
        print("   - Switch to production URL for real trading:")
        print("     export CRYPTO_COM_BASE_URL='https://api.crypto.com/exchange/v1'")
    
    if connection_ok and history_ok and live_trading:
        print()
        print("✅ System is ready for live trading!")
        print("   - LIVE_TRADING is enabled")
        print("   - API credentials are configured")
        print("   - Connection to exchange is working")
        print("   - Order history is accessible")
    
    print()
    print("=" * 70)

if __name__ == "__main__":
    main()






