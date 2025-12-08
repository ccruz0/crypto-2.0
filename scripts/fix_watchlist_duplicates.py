#!/usr/bin/env python3
"""
Fix duplicate trading pairs in watchlist_items table.

For each duplicate pair, keeps the entry with:
1. alert_enabled=True (if any)
2. Highest ID (most recent)
3. is_deleted=False

Marks other duplicates as is_deleted=True.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'backend'))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from collections import defaultdict
from sqlalchemy import and_

def fix_duplicates():
    """Fix duplicate pairs in watchlist."""
    db = SessionLocal()
    
    try:
        # Get all non-deleted items
        all_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        # Group by symbol
        pairs_by_symbol = defaultdict(list)
        for item in all_items:
            pairs_by_symbol[item.symbol].append(item)
        
        # Find duplicates
        duplicates = {symbol: items for symbol, items in pairs_by_symbol.items() if len(items) > 1}
        
        if not duplicates:
            print("✅ No duplicates found in watchlist_items")
            return 0
        
        print(f"Found {len(duplicates)} duplicate pairs:")
        for symbol, items in duplicates.items():
            print(f"  {symbol}: {len(items)} entries")
        
        print("\nFixing duplicates...")
        fixed_count = 0
        
        for symbol, items in duplicates.items():
            # Sort by priority:
            # 1. alert_enabled=True first
            # 2. Higher ID (more recent)
            items_sorted = sorted(items, key=lambda x: (
                not x.alert_enabled,  # False first (so True comes last)
                -x.id  # Higher ID first
            ))
            
            # Keep the first one (highest priority)
            keep_item = items_sorted[0]
            delete_items = items_sorted[1:]
            
            print(f"\n{symbol}:")
            print(f"  Keeping: ID {keep_item.id} (alert_enabled={keep_item.alert_enabled}, exchange={keep_item.exchange})")
            
            for item in delete_items:
                print(f"  Marking as deleted: ID {item.id} (alert_enabled={item.alert_enabled}, exchange={item.exchange})")
                item.is_deleted = True
                fixed_count += 1
        
        db.commit()
        print(f"\n✅ Fixed {fixed_count} duplicate entries")
        return 0
        
    except Exception as e:
        db.rollback()
        print(f"❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(fix_duplicates())
