#!/usr/bin/env python3
"""
Diagnostic script to test all alert types and verify Telegram sending behavior.

This script tests:
1. Executed order alerts (working path)
2. BUY signal alerts
3. SELL signal alerts
4. Monitoring alerts

Usage:
    Local:
        docker compose exec backend python scripts/diagnose_alert_types.py
    
    AWS:
        docker compose --profile aws exec backend-aws python scripts/diagnose_alert_types.py
        OR
        docker compose --profile aws exec market-updater python scripts/diagnose_alert_types.py
"""
import os
import sys
import logging
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import get_runtime_origin

# Configure logging to see diagnostic output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_executed_order_alert():
    """Test executed order alert (working path)"""
    print("\n" + "="*80)
    print("TEST 1: Executed Order Alert (Working Path)")
    print("="*80)
    print("Path: send_executed_order() → send_message() → get_runtime_origin()")
    print(f"Current RUNTIME_ORIGIN: {get_runtime_origin()}")
    print(f"RUNTIME_ORIGIN env var: {os.getenv('RUNTIME_ORIGIN', 'NOT_SET')}")
    
    result = telegram_notifier.send_executed_order(
        symbol="LDO_USD",
        side="BUY",
        price=2.50,
        quantity=100.0,
        total_usd=250.0,
        order_id="TEST_ORDER_123",
        order_type="LIMIT"
    )
    
    print(f"Result: {'✅ SENT' if result else '❌ FAILED'}")
    return result

def test_buy_signal_alert():
    """Test BUY signal alert"""
    print("\n" + "="*80)
    print("TEST 2: BUY Signal Alert")
    print("="*80)
    print("Path: send_buy_signal() → send_message(origin=...) → gatekeeper")
    print(f"Current RUNTIME_ORIGIN: {get_runtime_origin()}")
    print(f"RUNTIME_ORIGIN env var: {os.getenv('RUNTIME_ORIGIN', 'NOT_SET')}")
    
    result = telegram_notifier.send_buy_signal(
        symbol="LDO_USD",
        price=2.50,
        reason="🧪 DIAGNOSTIC TEST - RSI=35.0, Price=2.50",
        strategy_type="Swing",
        risk_approach="Conservative",
        source="LIVE ALERT"
    )
    
    print(f"Result: {'✅ SENT' if result else '❌ FAILED'}")
    return result

def test_sell_signal_alert():
    """Test SELL signal alert"""
    print("\n" + "="*80)
    print("TEST 3: SELL Signal Alert")
    print("="*80)
    print("Path: send_sell_signal() → send_message(origin=...) → gatekeeper")
    print(f"Current RUNTIME_ORIGIN: {get_runtime_origin()}")
    print(f"RUNTIME_ORIGIN env var: {os.getenv('RUNTIME_ORIGIN', 'NOT_SET')}")
    
    result = telegram_notifier.send_sell_signal(
        symbol="LDO_USD",
        price=2.60,
        reason="🧪 DIAGNOSTIC TEST - RSI=65.0, Price=2.60",
        strategy_type="Swing",
        risk_approach="Conservative",
        source="LIVE ALERT"
    )
    
    print(f"Result: {'✅ SENT' if result else '❌ FAILED'}")
    return result

def test_monitoring_alert():
    """Test monitoring alert (generic message)"""
    print("\n" + "="*80)
    print("TEST 4: Monitoring Alert (Generic Message)")
    print("="*80)
    print("Path: send_message() directly → gatekeeper")
    print(f"Current RUNTIME_ORIGIN: {get_runtime_origin()}")
    print(f"RUNTIME_ORIGIN env var: {os.getenv('RUNTIME_ORIGIN', 'NOT_SET')}")
    
    message = "🧪 DIAGNOSTIC TEST - Monitoring alert for LDO_USD"
    result = telegram_notifier.send_message(message)
    
    print(f"Result: {'✅ SENT' if result else '❌ FAILED'}")
    return result

def print_environment_info():
    """Print environment configuration"""
    print("\n" + "="*80)
    print("ENVIRONMENT CONFIGURATION")
    print("="*80)
    print(f"RUNTIME_ORIGIN: {os.getenv('RUNTIME_ORIGIN', 'NOT_SET')}")
    print(f"ENVIRONMENT: {os.getenv('ENVIRONMENT', 'NOT_SET')}")
    print(f"APP_ENV: {os.getenv('APP_ENV', 'NOT_SET')}")
    print(f"RUN_TELEGRAM: {os.getenv('RUN_TELEGRAM', 'NOT_SET')}")
    print(f"TELEGRAM_BOT_TOKEN: {'SET' if os.getenv('TELEGRAM_BOT_TOKEN') else 'NOT_SET'}")
    print(f"TELEGRAM_CHAT_ID: {os.getenv('TELEGRAM_CHAT_ID', 'NOT_SET')}")
    print(f"get_runtime_origin(): {get_runtime_origin()}")
    print(f"telegram_notifier.enabled: {telegram_notifier.enabled}")

def main():
    """Run all diagnostic tests"""
    print("\n" + "="*80)
    print("TELEGRAM ALERT DIAGNOSTIC SCRIPT")
    print("="*80)
    print("\nThis script tests all alert types to verify Telegram sending behavior.")
    print("Check the logs above for [TELEGRAM_GATEKEEPER] and [TELEGRAM_BLOCKED] messages.")
    
    print_environment_info()
    
    results = {
        "executed_order": test_executed_order_alert(),
        "buy_signal": test_buy_signal_alert(),
        "sell_signal": test_sell_signal_alert(),
        "monitoring": test_monitoring_alert(),
    }
    
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)
    for alert_type, result in results.items():
        status = "✅ SENT" if result else "❌ FAILED"
        print(f"{alert_type:20s}: {status}")
    
    all_passed = all(results.values())
    print(f"\nOverall: {'✅ ALL ALERTS SENT' if all_passed else '❌ SOME ALERTS FAILED'}")
    
    if not all_passed:
        print("\nTROUBLESHOOTING:")
        print("1. Check that RUNTIME_ORIGIN=AWS is set in docker-compose.yml for the service")
        print("2. Verify TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are set")
        print("3. Check logs for [TELEGRAM_GATEKEEPER] and [TELEGRAM_BLOCKED] messages")
        print("4. For signal alerts, ensure market-updater service has RUNTIME_ORIGIN=AWS")
    
    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
