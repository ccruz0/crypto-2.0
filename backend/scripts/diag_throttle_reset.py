#!/usr/bin/env python3
"""
Diagnostic script to test throttle reset after dashboard changes.

Usage:
    DIAG_SYMBOL=ETH_USDT python scripts/diag_throttle_reset.py

This script:
1. Runs one scheduler iteration and prints decision trace (BEFORE)
2. Simulates a dashboard change (calls actual API endpoint)
3. Runs scheduler iteration again (AFTER)
4. Extracts and prints only the trace snippets
"""

import os
import sys
import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Tuple

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set DIAG_SYMBOL before importing signal_monitor
os.environ["DIAG_SYMBOL"] = os.getenv("DIAG_SYMBOL", "ETH_USDT").upper()

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.services.signal_monitor import signal_monitor_service
from app.services.signal_throttle import (
    fetch_signal_states,
    reset_throttle_state,
    set_force_next_signal,
    build_strategy_key,
    compute_config_hash,
)
from app.services.strategy_profiles import resolve_strategy_profile

# Configure logging to capture to string buffer
log_buffer = []
stdout_buffer = []  # Capture stdout for print() statements

class ListHandler(logging.Handler):
    def emit(self, record):
        log_buffer.append(self.format(record))

class StdoutCapture:
    """Capture stdout for snippet extraction"""
    def __init__(self):
        self.buffer = []
        self.original_stdout = sys.stdout
    
    def write(self, text):
        if text.strip():  # Only capture non-empty lines
            self.buffer.append(text.rstrip())
        self.original_stdout.write(text)
    
    def flush(self):
        self.original_stdout.flush()

list_handler = ListHandler()
list_handler.setFormatter(logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s'))

logging.basicConfig(
    level=logging.INFO,
    handlers=[list_handler, logging.StreamHandler()]  # Both to buffer and console
)
logger = logging.getLogger(__name__)

# Capture stdout for print() statements
stdout_capture = StdoutCapture()
sys.stdout = stdout_capture

DIAG_SYMBOL = os.getenv("DIAG_SYMBOL", "ETH_USDT").upper()

def ensure_watchlist_item_exists(db, symbol: str) -> Tuple[WatchlistItem, bool]:
    """
    Ensure watchlist item exists for diagnostic symbol.
    Returns (item, was_created) tuple.
    """
    # Check if item exists (including deleted ones for restoration)
    item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol,
        WatchlistItem.exchange == "CRYPTO_COM"
    ).first()
    
    was_created = False
    if item:
        # Item exists - ensure it's configured for diagnostics
        if item.is_deleted or not item.alert_enabled:
            logger.info("=" * 80)
            logger.info(f"===== SEEDED WATCHLIST ITEM {symbol} =====")
            logger.info("=" * 80)
            logger.info(f"🔄 Updating existing item for diagnostics")
            
            # Restore/enable for diagnostics
            item.is_deleted = False
            item.alert_enabled = True  # Enable alerts so alert path runs
            if item.trade_enabled is None:
                item.trade_enabled = False  # Start disabled so toggle step is meaningful
            if item.trade_amount_usd is None or item.trade_amount_usd <= 0:
                item.trade_amount_usd = 100.0  # Safe default amount
            if not item.sl_tp_mode:
                item.sl_tp_mode = "conservative"  # Default strategy
            if item.min_price_change_pct is None:
                item.min_price_change_pct = 1.0  # Default threshold
            
            db.commit()
            db.refresh(item)
            logger.info(f"✅ Updated watchlist item for {symbol}:")
            logger.info(f"   alert_enabled=True, trade_enabled={item.trade_enabled}, trade_amount_usd={item.trade_amount_usd}")
            was_created = True  # Mark as "seeded" even if it existed
        else:
            # Item already exists and is properly configured
            logger.info(f"ℹ️ Watchlist item for {symbol} already exists and is configured")
    else:
        # Create new item with safe defaults for diagnostics
        logger.info("=" * 80)
        logger.info(f"===== SEEDED WATCHLIST ITEM {symbol} =====")
        logger.info("=" * 80)
        
        item = WatchlistItem(
            symbol=symbol,
            exchange="CRYPTO_COM",
            alert_enabled=True,  # Enable alerts so alert path runs
            trade_enabled=False,  # Start disabled so toggle step is meaningful
            trade_amount_usd=100.0,  # Safe default amount
            trade_on_margin=False,
            sl_tp_mode="conservative",  # Default strategy
            is_deleted=False,
            min_price_change_pct=1.0,  # Default threshold
        )
        db.add(item)
        db.commit()
        db.refresh(item)
        
        logger.info(f"✅ Created watchlist item for {symbol} with defaults:")
        logger.info(f"   alert_enabled=True, trade_enabled=False, trade_amount_usd=100.0")
        was_created = True
    
    return item, was_created

def get_watchlist_item(db, symbol: str) -> WatchlistItem:
    """Get watchlist item for symbol"""
    item = db.query(WatchlistItem).filter(
        WatchlistItem.symbol == symbol,
        WatchlistItem.is_deleted == False
    ).first()
    if not item:
        raise ValueError(f"Watchlist item not found for {symbol}")
    return item

def simulate_buy_alert_toggle(db, symbol: str, enabled: bool):
    """Simulate toggling buy alert (calls the actual endpoint logic)"""
    logger.info(f"🔄 Simulating buy alert toggle for {symbol}: {enabled}")
    
    item = get_watchlist_item(db, symbol)
    old_value = getattr(item, "buy_alert_enabled", False)
    
    if old_value == enabled:
        logger.info(f"  Buy alert already {enabled}, skipping")
        return
    
    # Update the field
    item.buy_alert_enabled = enabled
    item.alert_enabled = enabled or getattr(item, "sell_alert_enabled", False)
    db.commit()
    db.refresh(item)
    
    # Resolve strategy and reset throttle (simulating routes_market.py logic)
    strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
    strategy_key = build_strategy_key(strategy_type, risk_approach)
    
    # Get current price
    current_price = getattr(item, "price", None)
    if not current_price or current_price <= 0:
        try:
            from app.api.routes_dashboard import _get_market_data_for_symbol
            market_data = _get_market_data_for_symbol(db, symbol)
            if market_data:
                current_price = getattr(market_data, "price", None)
        except Exception:
            pass
    
    # Compute config hash
    config_hash = compute_config_hash({
        "alert_enabled": item.alert_enabled,
        "buy_alert_enabled": item.buy_alert_enabled,
        "sell_alert_enabled": getattr(item, "sell_alert_enabled", False),
        "trade_enabled": item.trade_enabled,
        "strategy_id": None,
        "strategy_name": item.sl_tp_mode,
        "min_price_change_pct": item.min_price_change_pct,
        "trade_amount_usd": item.trade_amount_usd,
    })
    
    # Reset throttle state
    reset_throttle_state(
        db=db,
        symbol=symbol,
        strategy_key=strategy_key,
        side="BUY",
        current_price=current_price,
        parameter_change_reason=f"Buy alert toggle: {old_value} -> {enabled}",
        config_hash=config_hash,
    )
    
    # Set force flag if enabling
    set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="BUY", enabled=enabled)
    
    db.commit()
    logger.info(f"✅ Buy alert toggle complete: {old_value} -> {enabled}")

def simulate_trade_toggle(db, symbol: str, enabled: bool):
    """Simulate toggling trade (calls the actual endpoint logic)"""
    logger.info(f"🔄 Simulating trade toggle for {symbol}: {enabled}")
    
    item = get_watchlist_item(db, symbol)
    old_value = item.trade_enabled
    
    if old_value == enabled:
        logger.info(f"  Trade already {enabled}, skipping")
        return
    
    # Update the field
    item.trade_enabled = enabled
    db.commit()
    db.refresh(item)
    
    # Resolve strategy and reset throttle (simulating routes_dashboard.py logic)
    strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
    strategy_key = build_strategy_key(strategy_type, risk_approach)
    
    # Get current price
    current_price = getattr(item, "price", None)
    if not current_price or current_price <= 0:
        try:
            from app.api.routes_dashboard import _get_market_data_for_symbol
            market_data = _get_market_data_for_symbol(db, symbol)
            if market_data:
                current_price = getattr(market_data, "price", None)
        except Exception:
            pass
    
    # Compute config hash
    config_hash = compute_config_hash({
        "alert_enabled": item.alert_enabled,
        "buy_alert_enabled": getattr(item, "buy_alert_enabled", False),
        "sell_alert_enabled": getattr(item, "sell_alert_enabled", False),
        "trade_enabled": item.trade_enabled,
        "strategy_id": None,
        "strategy_name": item.sl_tp_mode,
        "min_price_change_pct": item.min_price_change_pct,
        "trade_amount_usd": item.trade_amount_usd,
    })
    
    # Reset throttle state for both sides (trade affects both BUY and SELL)
    reset_throttle_state(
        db=db,
        symbol=symbol,
        strategy_key=strategy_key,
        side=None,  # Reset both
        current_price=current_price,
        parameter_change_reason=f"Trade toggle: {old_value} -> {enabled}",
        config_hash=config_hash,
    )
    
    # Set force flag if enabling
    if enabled:
        set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="BUY", enabled=True)
        set_force_next_signal(db, symbol=symbol, strategy_key=strategy_key, side="SELL", enabled=True)
    
    db.commit()
    logger.info(f"✅ Trade toggle complete: {old_value} -> {enabled}")

def check_throttle_state(db, symbol: str):
    """Check current throttle state"""
    item = get_watchlist_item(db, symbol)
    strategy_type, risk_approach = resolve_strategy_profile(symbol, db, item)
    strategy_key = build_strategy_key(strategy_type, risk_approach)
    
    snapshots = fetch_signal_states(db, symbol=symbol, strategy_key=strategy_key)
    
    logger.info(f"📊 Throttle state for {symbol} (strategy: {strategy_key}):")
    for side, snapshot in snapshots.items():
        if snapshot:
            logger.info(
                f"  {side}: last_price={snapshot.price}, "
                f"last_time={snapshot.timestamp}, "
                f"force_next_signal={snapshot.force_next_signal}, "
                f"config_hash={snapshot.config_hash[:16] if snapshot.config_hash else None}..."
            )
        else:
            logger.info(f"  {side}: No snapshot found")

def extract_trace_snippets():
    """Extract trace snippets from stdout buffer (print statements)"""
    snippets = []
    current_snippet = []
    in_trace = False
    
    # Combine stdout buffer (print statements) with log buffer (logger statements)
    all_lines = stdout_capture.buffer + log_buffer
    
    for line in all_lines:
        # Remove log prefixes if present (timestamp, logger name, etc.)
        # Keep the actual message content
        clean_line = line
        if " - " in line and ("INFO:" in line or "DEBUG:" in line or "WARNING:" in line or "ERROR:" in line):
            # Extract just the message part after the last " - "
            parts = line.split(" - ", 2)
            if len(parts) >= 3:
                clean_line = parts[2]  # Keep only the message part
        
        if "===== TRACE START" in clean_line:
            in_trace = True
            current_snippet = [clean_line]
        elif "===== TRACE END" in clean_line:
            if in_trace:
                current_snippet.append(clean_line)
                snippets.append("\n".join(current_snippet))
                current_snippet = []
                in_trace = False
        elif "===== TOGGLE" in clean_line:
            snippets.append(clean_line)
        elif in_trace:
            # Include all lines inside trace block (ALERT, TRADE, signal_detected, etc.)
            current_snippet.append(clean_line)
    
    return snippets

async def run_one_evaluation_cycle():
    """Run one evaluation cycle"""
    db = SessionLocal()
    try:
        await signal_monitor_service.monitor_signals(db)
    finally:
        db.close()

def toggle_trade_via_api(db, symbol: str, enabled: bool):
    """Toggle trade using the actual API endpoint logic"""
    logger.info("=" * 80)
    logger.info(f"===== TOGGLE TRADE {'ON' if enabled else 'OFF'} ({symbol}) =====")
    logger.info("=" * 80)
    
    # Import the actual endpoint function
    from app.api.routes_dashboard import update_watchlist_item_by_symbol
    
    # Call the endpoint with trade_enabled update
    try:
        # The endpoint expects a dict payload
        payload = {"trade_enabled": enabled}
        result = update_watchlist_item_by_symbol(
            symbol=symbol,
            payload=payload,
            db=db
        )
        logger.info(f"✅ Trade toggle successful: {result.get('message', 'OK') if isinstance(result, dict) else 'OK'}")
    except Exception as e:
        logger.error(f"❌ Trade toggle failed: {e}", exc_info=True)
        raise

def main():
    logger.info("=" * 80)
    logger.info(f"🔍 THROTTLE RESET DIAGNOSTIC - {DIAG_SYMBOL}")
    logger.info("=" * 80)
    
    db = SessionLocal()
    item_was_created = False
    try:
        # Ensure watchlist item exists (seed if needed)
        item, item_was_created = ensure_watchlist_item_exists(db, DIAG_SYMBOL)
        
        # BEFORE: Run one evaluation cycle
        logger.info("\n[BEFORE] Running evaluation cycle...")
        asyncio.run(run_one_evaluation_cycle())
        
        # TOGGLE: Toggle trade ON
        logger.info("\n[TOGGLE] Toggling trade ON...")
        toggle_trade_via_api(db, DIAG_SYMBOL, enabled=True)
        
        # AFTER: Run one evaluation cycle again
        logger.info("\n[AFTER] Running evaluation cycle again...")
        asyncio.run(run_one_evaluation_cycle())
        
        # Extract and print trace snippets
        logger.info("\n" + "=" * 80)
        logger.info("📋 EXTRACTED TRACE SNIPPETS")
        logger.info("=" * 80)
        snippets = extract_trace_snippets()
        for snippet in snippets:
            print(snippet)
            print()
        
        # Optional cleanup: if we created the item, mark it as deleted
        if item_was_created:
            logger.info("\n" + "=" * 80)
            logger.info("🧹 CLEANUP: Marking seeded item as deleted")
            logger.info("=" * 80)
            try:
                item.is_deleted = True
                item.alert_enabled = False
                item.trade_enabled = False
                db.commit()
                logger.info(f"✅ Cleaned up seeded item for {DIAG_SYMBOL}")
            except Exception as cleanup_err:
                logger.warning(f"⚠️ Cleanup failed (non-critical): {cleanup_err}")
        
        logger.info("=" * 80)
        logger.info("✅ Diagnostic complete")
        logger.info("=" * 80)
        
    except Exception as e:
        logger.error(f"❌ Error in diagnostic: {e}", exc_info=True)
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    main()

