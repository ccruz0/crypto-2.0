"""Script to test Crypto.com Exchange connection"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.brokers.crypto_com_trade import CryptoComTradeClient
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def test_connection():
    """Test Crypto.com Exchange connection"""
    print("\n" + "="*60)
    print("🧪 Testing Crypto.com Exchange Connection")
    print("="*60 + "\n")
    
    # Check environment variables
    print("📋 Environment Configuration:")
    print(f"  USE_CRYPTO_PROXY: {os.getenv('USE_CRYPTO_PROXY', 'not set')}")
    print(f"  CRYPTO_PROXY_URL: {os.getenv('CRYPTO_PROXY_URL', 'not set')}")
    print(f"  EXCHANGE_CUSTOM_BASE_URL: {os.getenv('EXCHANGE_CUSTOM_BASE_URL', 'not set')}")
    print(f"  EXCHANGE_CUSTOM_API_KEY: {'✅ Set' if os.getenv('EXCHANGE_CUSTOM_API_KEY') else '❌ Not set'}")
    print(f"  EXCHANGE_CUSTOM_API_SECRET: {'✅ Set' if os.getenv('EXCHANGE_CUSTOM_API_SECRET') else '❌ Not set'}")
    print(f"  LIVE_TRADING: {os.getenv('LIVE_TRADING', 'false')}")
    print()
    
    # Initialize client
    client = CryptoComTradeClient()
    
    # Test 1: Get account summary (balances)
    print("📊 Test 1: Getting account summary (balances)...")
    try:
        response = client.get_account_summary()
        if response:
            accounts = response.get('accounts', [])
            if accounts:
                print(f"✅ Success! Found {len(accounts)} account(s):")
                for acc in accounts[:5]:  # Show first 5
                    currency = acc.get('currency', 'N/A')
                    balance = acc.get('balance', '0')
                    available = acc.get('available', '0')
                    print(f"  • {currency}: Balance={balance}, Available={available}")
            else:
                print("⚠️  Response received but no accounts found")
                print(f"   Response: {response}")
        else:
            print("❌ No response received")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # Test 2: Get open orders
    print("📋 Test 2: Getting open orders...")
    try:
        response = client.get_open_orders()
        if response:
            orders = response.get('data', [])
            print(f"✅ Success! Found {len(orders)} open order(s)")
            if orders:
                for order in orders[:3]:  # Show first 3
                    symbol = order.get('instrument_name', 'N/A')
                    side = order.get('side', 'N/A')
                    status = order.get('status', 'N/A')
                    print(f"  • {symbol}: {side} - {status}")
        else:
            print("⚠️  No open orders or empty response")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print()
    
    # Test 3: Get order history
    print("📜 Test 3: Getting order history (last 5)...")
    try:
        response = client.get_order_history(page_size=5)
        if response:
            orders = response.get('data', [])
            print(f"✅ Success! Found {len(orders)} order(s) in history")
            if orders:
                for order in orders[:3]:  # Show first 3
                    symbol = order.get('instrument_name', 'N/A')
                    side = order.get('side', 'N/A')
                    status = order.get('status', 'N/A')
                    print(f"  • {symbol}: {side} - {status}")
        else:
            print("⚠️  No order history or empty response")
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    
    print("\n" + "="*60)
    print("✅ Connection test completed")
    print("="*60 + "\n")

if __name__ == "__main__":
    test_connection()
