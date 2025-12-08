#!/usr/bin/env python3
"""
Diagnostic script to test all Telegram alert paths and identify why some alerts don't reach Telegram.

This script triggers send_message() through all alert paths to diagnose:
- Which paths successfully send to Telegram
- Which paths fail and why
- Environment variable differences
- Origin detection issues
- Gatekeeper blocking

Usage:
    Local: docker compose exec backend python scripts/diagnose_telegram_paths.py
    AWS:   docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_paths.py
"""
import sys
import os
import logging
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.services.telegram_notifier import telegram_notifier
from app.core.runtime import get_runtime_origin

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def print_separator(title: str):
    """Print a visual separator"""
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80 + "\n")

def check_environment():
    """Check and print environment variables"""
    print_separator("ENVIRONMENT VARIABLES")
    
    env_vars = {
        "RUNTIME_ORIGIN": os.getenv("RUNTIME_ORIGIN", "NOT_SET"),
        "AWS_EXECUTION_ENV": os.getenv("AWS_EXECUTION_ENV", os.getenv("AWS_EXECUTION", "NOT_SET")),
        "RUN_TELEGRAM": os.getenv("RUN_TELEGRAM", "NOT_SET"),
        "TELEGRAM_BOT_TOKEN": "SET" if os.getenv("TELEGRAM_BOT_TOKEN") else "NOT_SET",
        "TELEGRAM_CHAT_ID": "SET" if os.getenv("TELEGRAM_CHAT_ID") else "NOT_SET",
        "APP_ENV": os.getenv("APP_ENV", "NOT_SET"),
        "ENVIRONMENT": os.getenv("ENVIRONMENT", "NOT_SET"),
    }
    
    for key, value in env_vars.items():
        print(f"  {key:25s} = {value}")
    
    print(f"\n  Runtime Origin (get_runtime_origin()): {get_runtime_origin()}")
    print(f"  Telegram Notifier Enabled: {telegram_notifier.enabled}")
    print(f"  Bot Token Present: {bool(telegram_notifier.bot_token)}")
    print(f"  Chat ID Present: {bool(telegram_notifier.chat_id)}")
    print()

def test_alert_path(alert_type: str, symbol: str, test_function):
    """Test a specific alert path and report results"""
    print(f"Testing: {alert_type} (Symbol: {symbol})")
    print(f"  Call started: {datetime.now().isoformat()}")
    
    try:
        result = test_function()
        
        if result:
            print(f"  ✅ RESULT: SUCCESS - Alert sent to Telegram")
        else:
            print(f"  ❌ RESULT: FAILURE - Alert NOT sent to Telegram (returned False)")
            print(f"  ⚠️  Check logs for [TELEGRAM_GATEKEEPER] or [TELEGRAM_RESPONSE] details")
    except Exception as e:
        print(f"  ❌ RESULT: EXCEPTION - {type(e).__name__}: {e}")
        print(f"  ⚠️  Check logs for full traceback")
    
    print()

def main():
    """Run diagnostic tests for all Telegram alert paths"""
    print_separator("TELEGRAM PATH DIAGNOSTICS")
    print("This script tests all alert paths to identify why some alerts don't reach Telegram.")
    print("Each test will log diagnostic information using [TELEGRAM_INVOKE], [TELEGRAM_GATEKEEPER],")
    print("[TELEGRAM_REQUEST], and [TELEGRAM_RESPONSE] tags.")
    print()
    
    # Check environment
    check_environment()
    
    # Test 1: Daily-style test alert (simulating daily sales report)
    print_separator("TEST 1: Daily Sales Report Style")
    test_alert_path(
        "DAILY_REPORT",
        "N/A",
        lambda: telegram_notifier.send_message(
            "[AWS] 📊 Test Reporte de Ventas - Daily Report Style\n\n"
            "This simulates the working daily sales report path.\n"
            "🤖 Trading Bot Automático"
        )
    )
    
    # Test 2: BUY signal alert
    print_separator("TEST 2: BUY Signal Alert")
    test_alert_path(
        "BUY_SIGNAL",
        "BTC_USDT",
        lambda: telegram_notifier.send_buy_signal(
            symbol="BTC_USDT",
            price=50000.0,
            reason="Test BUY signal for diagnostics",
            strategy_type="Swing",
            risk_approach="Conservative",
            source="LIVE ALERT"
        )
    )
    
    # Test 3: SELL signal alert
    print_separator("TEST 3: SELL Signal Alert")
    test_alert_path(
        "SELL_SIGNAL",
        "ETH_USDT",
        lambda: telegram_notifier.send_sell_signal(
            symbol="ETH_USDT",
            price=3000.0,
            reason="Test SELL signal for diagnostics",
            strategy_type="Swing",
            risk_approach="Conservative",
            source="LIVE ALERT"
        )
    )
    
    # Test 4: Order created alert
    print_separator("TEST 4: Order Created Alert")
    test_alert_path(
        "ORDER_CREATED",
        "SOL_USDT",
        lambda: telegram_notifier.send_order_created(
            symbol="SOL_USDT",
            side="BUY",
            price=100.0,
            quantity=1.0,
            order_id="TEST_ORDER_123",
            order_type="MARKET"
        )
    )
    
    # Test 5: Monitoring alert (direct send_message)
    print_separator("TEST 5: Monitoring Alert (Direct send_message)")
    test_alert_path(
        "MONITORING",
        "ADA_USDT",
        lambda: telegram_notifier.send_message(
            "🔔 Monitoring Alert: Test monitoring message for diagnostics"
        )
    )
    
    # Test 6: Debug test alert
    print_separator("TEST 6: Debug Test Alert")
    test_alert_path(
        "DEBUG_TEST",
        "TEST",
        lambda: telegram_notifier.debug_test_alert(
            alert_type="DEBUG_TEST",
            symbol="TEST",
            origin=None  # Let it default to get_runtime_origin()
        )
    )
    
    # Test 7: Debug test alert with explicit AWS origin
    print_separator("TEST 7: Debug Test Alert (Explicit AWS Origin)")
    test_alert_path(
        "DEBUG_TEST_AWS",
        "TEST",
        lambda: telegram_notifier.debug_test_alert(
            alert_type="DEBUG_TEST_AWS",
            symbol="TEST",
            origin="AWS"
        )
    )
    
    # Test 8: Simplified test alert (minimal message)
    print_separator("TEST 8: Simplified Test Alert")
    test_alert_path(
        "SIMPLIFIED",
        "N/A",
        lambda: telegram_notifier.send_message(
            "[AWS] TEST: Simplified alert"
        )
    )
    
    # Summary
    print_separator("SUMMARY")
    print("All tests completed. Review the logs above for:")
    print("  - [TELEGRAM_INVOKE] - Entry point diagnostics")
    print("  - [TELEGRAM_GATEKEEPER] - Gatekeeper decision details")
    print("  - [TELEGRAM_REQUEST] - Request being sent")
    print("  - [TELEGRAM_RESPONSE] - Response received")
    print()
    print("Compare the working daily sales report path with other paths to identify differences.")
    print()
    print("Next steps:")
    print("  1. Check which tests returned SUCCESS vs FAILURE")
    print("  2. Compare [TELEGRAM_GATEKEEPER] results between working and non-working paths")
    print("  3. Check [TELEGRAM_RESPONSE] for HTTP errors")
    print("  4. Verify environment variables are consistent across all execution contexts")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nFatal error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
