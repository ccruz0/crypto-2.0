#!/usr/bin/env python3
"""
Debug script to evaluate all watchlist symbols using the same logic as SignalMonitorService.

This script:
- Loads the same watchlist that SignalMonitorService uses
- For each symbol, runs the same decision logic (calculate_trading_signals)
- Checks throttle status and alert flags
- Outputs a table showing which symbols satisfy BUY/SELL criteria

Usage:
    python backend/scripts/debug_live_signals_all.py
    OR
    docker compose exec backend-aws python /app/scripts/debug_live_signals_all.py
"""
import sys
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

# Add backend directory to path for imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from sqlalchemy.orm import Session
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.watchlist_selector import select_preferred_watchlist_item, get_canonical_watchlist_item
from app.services.signal_evaluator import evaluate_signal_for_symbol
from app.models.market_price import MarketPrice, MarketData
from app.models.telegram_message import TelegramMessage
from price_fetcher import get_price_with_fallback
from datetime import timedelta
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)


def fetch_watchlist_items_sync(db: Session) -> List[WatchlistItem]:
    """
    Fetch watchlist items using the same logic as SignalMonitorService._fetch_watchlist_items_sync.
    
    Returns:
        List of WatchlistItem objects with alert_enabled = True
    """
    db.expire_all()
    
    try:
        db.rollback()
    except Exception:
        pass
    
    from sqlalchemy.orm import load_only
    columns = [
        WatchlistItem.id,
        WatchlistItem.symbol,
        WatchlistItem.exchange,
        WatchlistItem.alert_enabled,
        WatchlistItem.buy_alert_enabled,
        WatchlistItem.sell_alert_enabled,
        WatchlistItem.trade_enabled,
        WatchlistItem.trade_amount_usd,
        WatchlistItem.trade_on_margin,
        WatchlistItem.created_at,
    ]
    optional_columns = [
        getattr(WatchlistItem, "is_deleted", None),
        getattr(WatchlistItem, "take_profit", None),
        getattr(WatchlistItem, "stop_loss", None),
        getattr(WatchlistItem, "buy_target", None),
        getattr(WatchlistItem, "sell_price", None),
        getattr(WatchlistItem, "quantity", None),
        getattr(WatchlistItem, "purchase_price", None),
        getattr(WatchlistItem, "sold", None),
        getattr(WatchlistItem, "sl_tp_mode", None),
        getattr(WatchlistItem, "min_price_change_pct", None),
        getattr(WatchlistItem, "alert_cooldown_minutes", None),
    ]
    for col in optional_columns:
        if col is not None:
            columns.append(col)
    
    try:
        try:
            watchlist_rows = (
                db.query(WatchlistItem)
                .options(load_only(*columns))
                .filter(WatchlistItem.is_deleted == False)
                .all()
            )
        except Exception:
            db.rollback()
            watchlist_rows = (
                db.query(WatchlistItem)
                .options(load_only(*columns))
                .all()
            )
    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        db.rollback()
        return []
    
    if not watchlist_rows:
        logger.warning("⚠️ No watchlist rows found in database!")
        return []
    
    grouped: Dict[str, List[WatchlistItem]] = {}
    for row in watchlist_rows:
        symbol = (row.symbol or "").upper()
        if not symbol:
            continue
        grouped.setdefault(symbol, []).append(row)
    
    canonical_items: List[WatchlistItem] = []
    for symbol, rows in grouped.items():
        preferred = select_preferred_watchlist_item(rows, symbol)
        if not preferred:
            continue
        if getattr(preferred, "alert_enabled", False):
            canonical_items.append(preferred)
    
    logger.info(f"📊 Found {len(canonical_items)} canonical coins with alert_enabled = true")
    return canonical_items


def evaluate_symbol(
    db: Session,
    watchlist_item: WatchlistItem,
    monitor_service_instance=None
) -> Dict:
    """
    Evaluate a single symbol using the canonical signal evaluator.
    
    This function now delegates to evaluate_signal_for_symbol to ensure
    the debug script uses EXACTLY the same logic as SignalMonitorService.
    
    Returns:
        Dictionary with evaluation results (compatible with existing format_table_row)
    """
    symbol = watchlist_item.symbol
    
    # Refresh from DB (same as SignalMonitorService)
    fresh_item = get_canonical_watchlist_item(db, symbol)
    if fresh_item:
        watchlist_item.alert_enabled = fresh_item.alert_enabled
        watchlist_item.trade_enabled = fresh_item.trade_enabled
        watchlist_item.buy_alert_enabled = getattr(fresh_item, "buy_alert_enabled", False)
        watchlist_item.sell_alert_enabled = getattr(fresh_item, "sell_alert_enabled", False)
    
    # Check alert_enabled
    if not watchlist_item.alert_enabled:
        return {
            "symbol": symbol,
            "preset": "N/A",
            "decision": "WAIT",
            "buy_alert_enabled": False,
            "sell_alert_enabled": False,
            "trade_enabled": False,
            "can_emit_buy_alert": False,
            "can_emit_sell_alert": False,
            "throttle_buy_status": "N/A",
            "throttle_sell_status": "N/A",
            "throttle_buy_reason": "",
            "throttle_sell_reason": "",
            "price": None,
            "rsi": None,
            "ma50": None,
            "ma200": None,
            "ema10": None,
            "volume": None,
            "volume_ratio": None,
            "missing_indicators": [],
            "error": "alert_enabled=False",
        }
    
    # Use the canonical evaluator
    eval_result = evaluate_signal_for_symbol(db, watchlist_item, symbol)
    
    # Map to the format expected by format_table_row
    return {
        "symbol": symbol,
        "preset": eval_result["preset"],
        "decision": eval_result["decision"],
        "buy_alert_enabled": eval_result["buy_flag_allowed"],
        "sell_alert_enabled": eval_result["sell_flag_allowed"],
        "trade_enabled": bool(getattr(watchlist_item, "trade_enabled", False)),
        "can_emit_buy_alert": eval_result["can_emit_buy_alert"],
        "can_emit_sell_alert": eval_result["can_emit_sell_alert"],
        "throttle_buy_status": eval_result["throttle_status_buy"],
        "throttle_sell_status": eval_result["throttle_status_sell"],
        "throttle_buy_reason": eval_result["throttle_reason_buy"],
        "throttle_sell_reason": eval_result["throttle_reason_sell"],
        "price": eval_result["price"],
        "rsi": eval_result["rsi"],
        "ma50": eval_result["ma50"],
        "ma200": eval_result["ma200"],
        "ema10": eval_result["ema10"],
        "volume": None,  # Not in eval_result, but not used in format_table_row
        "volume_ratio": eval_result["volume_ratio"],
        "missing_indicators": eval_result["missing_indicators"],
        "error": eval_result["error"],
    }


def format_table_row(result: Dict) -> str:
    """Format a single row for the output table."""
    symbol = result["symbol"]
    preset = result["preset"]
    decision = result["decision"]
    buy_alert = "✓" if result["buy_alert_enabled"] else "✗"
    sell_alert = "✓" if result["sell_alert_enabled"] else "✗"
    trade = "✓" if result["trade_enabled"] else "✗"
    can_emit_buy = "✓" if result["can_emit_buy_alert"] else "✗"
    can_emit_sell = "✓" if result["can_emit_sell_alert"] else "✗"
    buy_throttle = result["throttle_buy_status"]
    sell_throttle = result["throttle_sell_status"]
    missing = ",".join(result["missing_indicators"]) if result["missing_indicators"] else "-"
    
    if result["error"]:
        return f"{symbol:12} | {preset:20} | ERROR: {result['error']}"
    
    return (
        f"{symbol:12} | {preset:20} | {decision:6} | {buy_alert:3} | {sell_alert:3} | "
        f"{trade:3} | {can_emit_buy:3} | {buy_throttle:8} | {can_emit_sell:3} | "
        f"{sell_throttle:8} | {missing:15}"
    )


def get_recent_alerts(db: Session, minutes: int = 30) -> Dict[str, List[Dict]]:
    """
    Get alerts emitted in the last N minutes, grouped by symbol.
    
    Returns:
        Dict mapping symbol to list of alert dicts with timestamp, side, blocked status
    """
    try:
        cutoff_time = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        alerts = (
            db.query(TelegramMessage)
            .filter(TelegramMessage.timestamp >= cutoff_time)
            .order_by(TelegramMessage.timestamp.desc())
            .all()
        )
        
        result: Dict[str, List[Dict]] = {}
        for alert in alerts:
            symbol = alert.symbol or "UNKNOWN"
            if symbol not in result:
                result[symbol] = []
            
            # Determine side from message content
            side = "UNKNOWN"
            if "BUY" in alert.message.upper() or "🟢" in alert.message:
                side = "BUY"
            elif "SELL" in alert.message.upper() or "🔴" in alert.message:
                side = "SELL"
            
            result[symbol].append({
                "timestamp": alert.timestamp.isoformat() if alert.timestamp else None,
                "side": side,
                "blocked": alert.blocked,
                "message": alert.message[:80],
            })
        
        return result
    except Exception as e:
        logger.warning(f"Error fetching recent alerts: {e}")
        return {}


def main():
    """Main entry point."""
    db: Optional[Session] = None
    try:
        db = SessionLocal()
        
        # Get recent alerts (last 30 minutes)
        recent_alerts = get_recent_alerts(db, minutes=30)
        
        # Fetch watchlist items
        watchlist_items = fetch_watchlist_items_sync(db)
        
        if not watchlist_items:
            print("⚠️ No watchlist items found with alert_enabled=True")
            return
        
        print(f"\n{'='*120}")
        print(f"Evaluating {len(watchlist_items)} symbols from watchlist")
        print(f"Recent alerts (last 30 min): {sum(len(v) for v in recent_alerts.values())} alerts across {len(recent_alerts)} symbols")
        print(f"{'='*120}\n")
        
        # Print header
        header = (
            f"{'SYMBOL':12} | {'PRESET':20} | {'DECISION':6} | {'BUY':3} | {'SELL':3} | "
            f"{'TRADE':3} | {'CAN_BUY':3} | {'BUY_THR':8} | {'CAN_SELL':3} | "
            f"{'SELL_THR':8} | {'MISSING':15}"
        )
        print(header)
        print("-" * 120)
        
        results = []
        buy_signals = []
        sell_signals = []
        
        # Evaluate each symbol
        for item in watchlist_items:
            result = evaluate_symbol(db, item)
            
            # Add recent alerts info
            symbol_alerts = recent_alerts.get(result["symbol"], [])
            if symbol_alerts:
                alert_summary = []
                for alert in symbol_alerts:
                    status = "BLOCKED" if alert["blocked"] else "SENT"
                    alert_summary.append(f"{alert['side']}:{status}")
                result["recent_alerts"] = " | ".join(alert_summary)
            else:
                result["recent_alerts"] = "-"
            
            results.append(result)
            print(format_table_row(result))
            
            if result["decision"] == "BUY" and result["can_emit_buy_alert"]:
                buy_signals.append(result["symbol"])
            elif result["decision"] == "SELL" and result["can_emit_sell_alert"]:
                sell_signals.append(result["symbol"])
        
        # Print summary
        print("\n" + "=" * 120)
        print("SUMMARY")
        print("=" * 120)
        print(f"BUY_SIGNALS_NOW: {buy_signals if buy_signals else '[]'}")
        print(f"SELL_SIGNALS_NOW: {sell_signals if sell_signals else '[]'}")
        print(f"\nTotal symbols evaluated: {len(results)}")
        print(f"Symbols with BUY decision: {sum(1 for r in results if r['decision'] == 'BUY')}")
        print(f"Symbols with SELL decision: {sum(1 for r in results if r['decision'] == 'SELL')}")
        print(f"Symbols with WAIT decision: {sum(1 for r in results if r['decision'] == 'WAIT')}")
        print(f"Symbols that can emit BUY alert: {sum(1 for r in results if r['can_emit_buy_alert'])}")
        print(f"Symbols that can emit SELL alert: {sum(1 for r in results if r['can_emit_sell_alert'])}")
        
        # Show recent alerts summary
        if recent_alerts:
            print(f"\nRecent alerts (last 30 minutes):")
            for symbol, alerts in sorted(recent_alerts.items()):
                for alert in alerts:
                    status = "BLOCKED" if alert["blocked"] else "SENT"
                    print(f"  {symbol}: {alert['side']} - {status} ({alert['timestamp']})")
        else:
            print(f"\nNo alerts emitted in the last 30 minutes")
        
    except Exception as e:
        logger.error(f"Error in main: {e}", exc_info=True)
        print(f"❌ Error: {e}")
    finally:
        if db:
            db.close()


if __name__ == "__main__":
    main()

