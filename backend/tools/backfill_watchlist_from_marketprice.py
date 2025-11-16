#!/usr/bin/env python3
"""
Backfill script to create watchlist_items entries from MarketPrice.

This script ensures all symbols in MarketPrice have a corresponding row in watchlist_items
with is_deleted=False, so the Watchlist endpoint can show all available coins.

The script is idempotent - running it multiple times will not create duplicates.

Usage:
    cd backend
    python tools/backfill_watchlist_from_marketprice.py
"""

import sys
import os

# Add parent directory to path to import app modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.market_price import MarketPrice

def should_exclude_symbol(symbol: str, price: float) -> bool:
    """
    Determine if a symbol should be excluded from backfill.
    
    Excludes:
    - Test symbols (symbols starting with 'TEST_')
    - Symbols with zero or invalid price (optional - currently not excluding)
    
    Returns True if symbol should be excluded.
    """
    symbol_upper = symbol.upper()
    
    # Exclude test symbols
    if symbol_upper.startswith('TEST_') or symbol_upper == 'TEST':
        return True
    
    # Optionally exclude zero-price symbols (currently disabled to include all real coins)
    # if price is not None and price <= 0:
    #     return True
    
    return False

def main():
    db = SessionLocal()
    try:
        print("=" * 60)
        print("WATCHLIST BACKFILL FROM MARKETPRICE")
        print("=" * 60)
        
        # Get all MarketPrice entries
        market_prices = db.query(MarketPrice).all()
        print(f"Found {len(market_prices)} symbols in MarketPrice")
        
        # Get existing watchlist_items
        existing_watchlist_items = db.query(WatchlistItem).all()
        existing_by_symbol = {item.symbol: item for item in existing_watchlist_items}
        
        print(f"Found {len(existing_watchlist_items)} existing watchlist_items entries")
        
        # Process each MarketPrice symbol
        created_count = 0
        reactivated_count = 0
        skipped_count = 0
        excluded_count = 0
        
        for mp in market_prices:
            symbol = mp.symbol
            price = mp.price or 0.0
            
            # Check if symbol should be excluded
            if should_exclude_symbol(symbol, price):
                excluded_count += 1
                continue
            
            # Check if entry already exists
            existing_item = existing_by_symbol.get(symbol)
            
            if existing_item:
                # Entry exists
                if existing_item.is_deleted:
                    # Reactivate deleted entry
                    # Decision: Reactivate because this is a migration/backfill operation
                    # The user can delete again if they don't want the symbol
                    existing_item.is_deleted = False
                    # Reset config fields to safe defaults (in case they were set before deletion)
                    existing_item.trade_enabled = False
                    existing_item.alert_enabled = False
                    existing_item.trade_on_margin = False
                    existing_item.trade_amount_usd = None
                    existing_item.sl_percentage = None
                    existing_item.tp_percentage = None
                    existing_item.sl_price = None
                    existing_item.tp_price = None
                    existing_item.buy_target = None
                    existing_item.take_profit = None
                    existing_item.stop_loss = None
                    existing_item.sl_tp_mode = "conservative"
                    existing_item.order_status = "PENDING"
                    reactivated_count += 1
                    print(f"  ✓ Reactivated: {symbol}")
                else:
                    # Already active - skip
                    skipped_count += 1
            else:
                # No entry exists - create new one
                new_item = WatchlistItem(
                    symbol=symbol,
                    exchange="CRYPTO_COM",  # Default exchange
                    is_deleted=False,
                    trade_enabled=False,
                    alert_enabled=False,
                    trade_on_margin=False,
                    trade_amount_usd=None,
                    sl_percentage=None,
                    tp_percentage=None,
                    sl_price=None,
                    tp_price=None,
                    buy_target=None,
                    take_profit=None,
                    stop_loss=None,
                    sl_tp_mode="conservative",
                    order_status="PENDING",
                )
                db.add(new_item)
                created_count += 1
                print(f"  + Created: {symbol}")
        
        # Commit all changes
        db.commit()
        
        print("\n" + "=" * 60)
        print("BACKFILL SUMMARY")
        print("=" * 60)
        print(f"Total MarketPrice symbols processed: {len(market_prices)}")
        print(f"  - Created: {created_count}")
        print(f"  - Reactivated: {reactivated_count}")
        print(f"  - Skipped (already active): {skipped_count}")
        print(f"  - Excluded (test symbols): {excluded_count}")
        print(f"\nTotal watchlist_items entries after backfill: {len(existing_watchlist_items) + created_count}")
        print("=" * 60)
        
        # Verify final state
        active_count = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).count()
        print(f"\n✅ Active watchlist_items entries: {active_count}")
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}", file=sys.stderr)
        db.rollback()
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        db.close()

if __name__ == "__main__":
    main()

