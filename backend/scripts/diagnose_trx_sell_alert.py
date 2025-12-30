#!/usr/bin/env python3
"""
Diagnostic script to check why TRX SELL alerts are not being sent.

This script checks:
1. Watchlist configuration for TRX_USDT
2. Alert flags (alert_enabled, sell_alert_enabled)
3. Trade flags (trade_enabled, trade_amount_usd)
4. Last signal state and throttling information
5. Recent alerts/orders for TRX_USDT
"""

import sys
import os
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_throttle import fetch_signal_states, build_strategy_key
from app.services.strategy_profiles import resolve_strategy_profile
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.services.brokers.crypto_com_trade import trade_client
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

def get_watchlist_item(db: Session, symbol: str) -> Optional[WatchlistItem]:
    """Get watchlist item for symbol."""
    return db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol,
        WatchlistItem.is_deleted == False
    ).first()

def get_last_signal_states(db: Session, symbol: str) -> Dict[str, Any]:
    """Get last signal states for symbol."""
    try:
        from app.services.watchlist_selector import get_canonical_watchlist_item
        watchlist_item = get_canonical_watchlist_item(db, symbol)
        if not watchlist_item:
            return {}
        
        strategy_type, risk_approach = resolve_strategy_profile(symbol, db, watchlist_item)
        strategy_key = build_strategy_key(strategy_type, risk_approach)
        signal_states = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
        return signal_states
    except Exception as e:
        print(f"⚠️ Error fetching signal states: {e}")
        return {}

def get_recent_orders(db: Session, symbol: str, hours: int = 24) -> list:
    """Get recent orders for symbol."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    orders = db.query(ExchangeOrder).filter(
        ExchangeOrder.symbol == symbol,
        ExchangeOrder.side == OrderSideEnum.SELL,
        ExchangeOrder.created_at >= cutoff
    ).order_by(ExchangeOrder.created_at.desc()).limit(10).all()
    return orders

def format_timestamp(dt: Optional[datetime]) -> str:
    """Format timestamp for display."""
    if not dt:
        return "N/A"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%d %H:%M:%S UTC")

def format_price(price: Optional[float]) -> str:
    """Format price for display."""
    if price is None:
        return "N/A"
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.2f}"
    elif price >= 0.01:
        return f"${price:.4f}"
    else:
        return f"${price:.8f}"

def diagnose_trx_sell_alert():
    """Main diagnostic function."""
    db: Session = SessionLocal()
    
    try:
        print("=" * 80)
        print("TRX_USDT SELL ORDER CREATION DIAGNOSTIC")
        print("=" * 80)
        print("This script checks why SELL orders are not being created automatically")
        print("(assuming SELL alerts are already being sent)")
        print()
        
        # Check watchlist configuration
        print("📋 WATCHLIST CONFIGURATION")
        print("-" * 80)
        watchlist_item = get_watchlist_item(db, "TRX_USDT")
        
        if not watchlist_item:
            print("❌ TRX_USDT not found in watchlist!")
            print("   → Add TRX_USDT to watchlist first")
            return
        
        print(f"✅ TRX_USDT found in watchlist")
        print(f"   Symbol: {watchlist_item.symbol}")
        print(f"   Exchange: {watchlist_item.exchange}")
        print()
        
        # Alert flags
        alert_enabled = getattr(watchlist_item, 'alert_enabled', False)
        sell_alert_enabled = getattr(watchlist_item, 'sell_alert_enabled', False)
        buy_alert_enabled = getattr(watchlist_item, 'buy_alert_enabled', False)
        
        print("🔔 ALERT FLAGS")
        print(f"   alert_enabled (master): {'✅ TRUE' if alert_enabled else '❌ FALSE'}")
        print(f"   sell_alert_enabled: {'✅ TRUE' if sell_alert_enabled else '❌ FALSE'}")
        print(f"   buy_alert_enabled: {'✅ TRUE' if buy_alert_enabled else '❌ FALSE'}")
        
        if not alert_enabled:
            print("   ⚠️  ISSUE: alert_enabled is FALSE - alerts will not be sent!")
        if not sell_alert_enabled:
            print("   ⚠️  ISSUE: sell_alert_enabled is FALSE - SELL alerts will not be sent!")
        
        if alert_enabled and sell_alert_enabled:
            print("   ✅ Both flags are enabled - alerts should be sent")
        print()
        
        # Trade flags
        trade_enabled = getattr(watchlist_item, 'trade_enabled', False)
        trade_amount_usd = getattr(watchlist_item, 'trade_amount_usd', None)
        trade_on_margin = getattr(watchlist_item, 'trade_on_margin', False)
        
        print("💰 TRADE FLAGS")
        print(f"   trade_enabled: {'✅ TRUE' if trade_enabled else '❌ FALSE'}")
        print(f"   trade_amount_usd: {format_price(trade_amount_usd) if trade_amount_usd else '❌ NOT SET'}")
        print(f"   trade_on_margin: {'✅ TRUE' if trade_on_margin else '❌ FALSE'}")
        
        if not trade_enabled:
            print("   ⚠️  ISSUE: trade_enabled is FALSE - orders will not be created automatically!")
        if not trade_amount_usd or trade_amount_usd <= 0:
            print("   ⚠️  ISSUE: trade_amount_usd is not set or <= 0 - orders will not be created!")
        
        if trade_enabled and trade_amount_usd and trade_amount_usd > 0:
            print("   ✅ Trade is enabled and amount is configured - orders should be created")
        print()
        
        # Throttling configuration
        min_price_change_pct = getattr(watchlist_item, 'min_price_change_pct', None)
        alert_cooldown_minutes = getattr(watchlist_item, 'alert_cooldown_minutes', None)
        
        print("⏱️  THROTTLING CONFIGURATION")
        print(f"   min_price_change_pct: {min_price_change_pct if min_price_change_pct else 'Strategy default'}")
        print(f"   alert_cooldown_minutes: {alert_cooldown_minutes if alert_cooldown_minutes else 'Strategy default'}")
        print()
        
        # Signal states
        print("📊 SIGNAL STATES (THROTTLING)")
        print("-" * 80)
        signal_states = get_last_signal_states(db, "TRX_USDT")
        
        if signal_states:
            for side, snapshot in signal_states.items():
                if snapshot:
                    print(f"   {side} Signal:")
                    print(f"      Last price: {format_price(snapshot.price)}")
                    print(f"      Last timestamp: {format_timestamp(snapshot.timestamp)}")
                    if snapshot.timestamp:
                        elapsed = (datetime.now(timezone.utc) - snapshot.timestamp).total_seconds() / 60
                        print(f"      Time since last: {elapsed:.1f} minutes")
                    print(f"      Strategy key: {snapshot.strategy_key}")
                    print(f"      Source: {snapshot.source}")
                    print(f"      Emit reason: {snapshot.emit_reason}")
                    print()
        else:
            print("   ℹ️  No previous signal states found (first signal)")
            print()
        
        # Balance check for SELL orders
        print("💰 BALANCE CHECK (for SELL orders)")
        print("-" * 80)
        if trade_enabled and trade_amount_usd and trade_amount_usd > 0:
            base_currency = "TRX"  # For TRX_USDT
            try:
                account_summary = trade_client.get_account_summary()
                available_balance = 0
                
                if 'accounts' in account_summary or 'data' in account_summary:
                    accounts = account_summary.get('accounts') or account_summary.get('data', {}).get('accounts', [])
                    for acc in accounts:
                        currency = acc.get('currency', '').upper()
                        if currency == base_currency:
                            available = float(acc.get('available', '0') or '0')
                            available_balance = available
                            break
                
                # Get current price (estimate or use a default)
                # For SELL orders, we need base currency (TRX), not USDT
                print(f"   Base currency needed: {base_currency}")
                print(f"   Available balance: {available_balance:.8f} {base_currency}")
                
                # Estimate required quantity (would need current price, but this gives an idea)
                print(f"   Trade amount: ${trade_amount_usd:,.2f} USD")
                print(f"   ⚠️  Note: Required quantity depends on current TRX price")
                print(f"      (Required qty = ${trade_amount_usd:,.2f} / current_TRX_price)")
                print()
                
                if available_balance == 0:
                    print(f"   ❌ ISSUE: No {base_currency} balance available!")
                    print(f"      → You need to buy {base_currency} first before creating SELL orders")
                    print()
            except Exception as e:
                print(f"   ⚠️  Could not check balance: {e}")
                print()
        else:
            print("   ℹ️  Skipping balance check (trade not enabled or amount not set)")
            print()
        
        # Recent orders
        print("📦 RECENT SELL ORDERS (last 24 hours)")
        print("-" * 80)
        recent_orders = get_recent_orders(db, "TRX_USDT", hours=24)
        
        if recent_orders:
            for order in recent_orders:
                print(f"   Order ID: {order.exchange_order_id}")
                print(f"   Status: {order.status}")
                print(f"   Price: {format_price(float(order.price or 0))}")
                print(f"   Quantity: {order.quantity}")
                print(f"   Created: {format_timestamp(order.created_at)}")
                print()
        else:
            print("   ℹ️  No recent SELL orders found")
            print()
        
        # Recommendations
        print("💡 RECOMMENDATIONS FOR ORDER CREATION")
        print("-" * 80)
        
        issues = []
        order_issues = []
        
        # Alert issues (if alerts aren't being sent)
        if not alert_enabled:
            issues.append("Enable 'alert_enabled' in watchlist configuration")
        if not sell_alert_enabled:
            issues.append("Enable 'sell_alert_enabled' in watchlist configuration")
        
        # Order creation issues (most important for this case)
        if not trade_enabled:
            order_issues.append("❌ CRITICAL: Enable 'trade_enabled' in watchlist configuration")
        if not trade_amount_usd or trade_amount_usd <= 0:
            order_issues.append("❌ CRITICAL: Set 'trade_amount_usd' to a value > 0")
        
        if order_issues:
            print("   🚨 ORDER CREATION ISSUES:")
            for i, issue in enumerate(order_issues, 1):
                print(f"      {i}. {issue}")
            print()
        
        if issues:
            print("   ⚠️  ALERT ISSUES (if alerts aren't being sent):")
            for i, issue in enumerate(issues, 1):
                print(f"      {i}. {issue}")
            print()
        
        if signal_states.get("SELL"):
            sell_snapshot = signal_states["SELL"]
            if sell_snapshot and sell_snapshot.timestamp:
                elapsed_minutes = (datetime.now(timezone.utc) - sell_snapshot.timestamp).total_seconds() / 60
                cooldown = alert_cooldown_minutes or 5.0  # Default cooldown
                if elapsed_minutes < cooldown:
                    remaining = cooldown - elapsed_minutes
                    print(f"   ⏱️  Throttling: Wait {remaining:.1f} more minutes for cooldown to expire (last SELL alert was {elapsed_minutes:.1f} minutes ago)")
                    print()
        
        if not order_issues and not issues:
            print("   ✅ Configuration looks good!")
            print("   → Check backend logs for order creation errors")
            print("   → Look for '[DIAGNOSTIC] TRX_USDT SELL order' messages in logs")
            print("   → Check for balance issues or other blocking reasons")
        
        print()
        print("=" * 80)
        
    except Exception as e:
        print(f"❌ Error during diagnosis: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    diagnose_trx_sell_alert()

