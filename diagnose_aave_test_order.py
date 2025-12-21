#!/usr/bin/env python3
"""
Diagnostic script to identify why AAVE test order failed.
This script checks common failure points and provides recommendations.
"""

import sys
import os
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent / "backend"))

def diagnose_aave_test_order():
    """Diagnose why AAVE test order failed"""
    print("=" * 80)
    print("AAVE TEST ORDER DIAGNOSTIC")
    print("=" * 80)
    print()
    
    print("Common reasons why test orders fail:")
    print()
    
    issues = [
        {
            "issue": "Trade not enabled",
            "check": "trade_enabled = False in watchlist",
            "solution": "Enable 'Trade' = YES in Dashboard for AAVE_USDT",
            "code_location": "routes_test.py:338"
        },
        {
            "issue": "Amount USD not configured",
            "check": "trade_amount_usd is None or <= 0",
            "solution": "Configure 'Amount USD' > 0 in Dashboard for AAVE_USDT",
            "code_location": "routes_test.py:355"
        },
        {
            "issue": "Insufficient balance (SPOT orders)",
            "check": "Available balance < required amount * 1.1",
            "solution": "Deposit more funds or reduce order size",
            "code_location": "signal_monitor.py:2492"
        },
        {
            "issue": "Open orders limit reached",
            "check": "3 or more open orders for AAVE_USDT",
            "solution": "Wait for orders to complete or cancel some orders",
            "code_location": "signal_monitor.py:2598"
        },
        {
            "issue": "Portfolio value exceeds limit",
            "check": "Portfolio value > 3x trade_amount_usd",
            "solution": "Wait for portfolio value to decrease or increase trade_amount_usd",
            "code_location": "signal_monitor.py:portfolio_check"
        },
        {
            "issue": "Recent orders cooldown",
            "check": "Order created within last 5 minutes",
            "solution": "Wait 5 minutes before creating another order",
            "code_location": "signal_monitor.py:2629"
        },
        {
            "issue": "Exchange API error 306",
            "check": "INSUFFICIENT_AVAILABLE_BALANCE",
            "solution": "Deposit more funds or use margin trading",
            "code_location": "signal_monitor.py:error_handling"
        },
        {
            "issue": "Exchange API error 609",
            "check": "INSUFFICIENT_MARGIN",
            "solution": "Reduce leverage or use SPOT trading",
            "code_location": "signal_monitor.py:2723"
        },
        {
            "issue": "Dry run mode",
            "check": "LIVE_TRADING=false",
            "solution": "Enable live trading if you want real orders",
            "code_location": "signal_monitor.py:2639"
        },
        {
            "issue": "Order creation returned None",
            "check": "Order creation logic returned None",
            "solution": "Check backend logs for specific error messages",
            "code_location": "signal_monitor.py:return None"
        }
    ]
    
    for i, issue in enumerate(issues, 1):
        print(f"{i}. {issue['issue']}")
        print(f"   Check: {issue['check']}")
        print(f"   Solution: {issue['solution']}")
        print(f"   Code: {issue['code_location']}")
        print()
    
    print("=" * 80)
    print("HOW TO DIAGNOSE:")
    print("=" * 80)
    print()
    print("1. Check Dashboard Configuration:")
    print("   - Go to Watchlist tab")
    print("   - Find AAVE_USDT")
    print("   - Verify 'Trade' = YES")
    print("   - Verify 'Amount USD' > 0")
    print()
    print("2. Use Diagnostic Endpoint:")
    print("   curl http://localhost:8002/api/test/diagnose-alert/AAVE_USDT")
    print()
    print("3. Check Backend Logs:")
    print("   Look for messages containing:")
    print("   - '[Background] Error creating order'")
    print("   - 'Order creation returned None'")
    print("   - 'SEGURIDAD 2/2'")
    print("   - 'BLOCKED at final check'")
    print("   - 'BLOQUEO POR BALANCE'")
    print("   - 'ERROR 609' or 'ERROR 306'")
    print()
    print("4. Check Telegram Messages:")
    print("   - Look for error notifications about AAVE_USDT")
    print("   - Messages will indicate the specific failure reason")
    print()
    print("5. Run Diagnostic Script:")
    print("   python backend/scripts/diagnose_simulate_alert.py AAVE_USDT")
    print()
    
    print("=" * 80)
    print("QUICK FIXES:")
    print("=" * 80)
    print()
    print("If you see 'Trade not enabled':")
    print("  → Enable 'Trade' = YES in Dashboard")
    print()
    print("If you see 'Amount USD not configured':")
    print("  → Set 'Amount USD' to a value > 0 in Dashboard")
    print()
    print("If you see 'Balance insufficient':")
    print("  → Deposit more funds or reduce order size")
    print()
    print("If you see 'Open orders limit':")
    print("  → Wait for existing orders to complete")
    print()
    print("If you see 'Portfolio value exceeds limit':")
    print("  → Wait for portfolio value to decrease or increase trade_amount_usd")
    print()
    print("If you see 'Recent orders cooldown':")
    print("  → Wait 5 minutes before trying again")
    print()
    print("If you see API errors (306, 609, etc.):")
    print("  → Check exchange API status and account balance")
    print()

if __name__ == "__main__":
    diagnose_aave_test_order()







