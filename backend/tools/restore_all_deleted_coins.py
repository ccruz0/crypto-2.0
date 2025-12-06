#!/usr/bin/env python3
"""
Restore all deleted coins from dashboard by setting is_deleted=False for all watchlist items.
This ensures no coins are hidden from the dashboard.
"""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def main():
    db = SessionLocal()
    
    try:
        print("="*80)
        print("RESTORING ALL DELETED COINS FROM DASHBOARD")
        print("="*80)
        
        # Find all deleted items
        deleted_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == True
        ).all()
        
        print(f"\n1. FOUND {len(deleted_items)} DELETED ITEMS:")
        print("-"*80)
        
        if deleted_items:
            symbols = sorted(set(item.symbol for item in deleted_items))
            print(f"   Symbols to restore: {', '.join(symbols[:20])}")
            if len(symbols) > 20:
                print(f"   ... and {len(symbols) - 20} more")
            
            # Restore all deleted items
            restored_count = 0
            for item in deleted_items:
                if item.is_deleted:
                    item.is_deleted = False
                    restored_count += 1
            
            db.commit()
            print(f"\n✅ Restored {restored_count} items (set is_deleted=False)")
        else:
            print("   ✅ No deleted items found - all coins are visible")
        
        # Show summary
        print("\n2. SUMMARY:")
        print("-"*80)
        all_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        
        # Deduplicate by symbol
        seen_symbols = {}
        for item in all_items:
            if item.symbol not in seen_symbols:
                seen_symbols[item.symbol] = item
            else:
                # Keep the most recent one
                existing = seen_symbols[item.symbol]
                if item.created_at and existing.created_at:
                    if item.created_at > existing.created_at:
                        seen_symbols[item.symbol] = item
        
        unique_symbols = len(seen_symbols)
        print(f"✅ Total non-deleted items: {len(all_items)}")
        print(f"✅ Unique symbols: {unique_symbols}")
        
        print(f"\nFirst 30 symbols:")
        for i, symbol in enumerate(sorted(seen_symbols.keys())[:30], 1):
            print(f"   {i:2d}. {symbol}")
        if unique_symbols > 30:
            print(f"   ... and {unique_symbols - 30} more")
        
        # Check for duplicates
        print("\n3. CHECKING FOR DUPLICATES:")
        print("-"*80)
        from collections import Counter
        symbol_counts = Counter(item.symbol for item in all_items)
        duplicates = {symbol: count for symbol, count in symbol_counts.items() if count > 1}
        
        if duplicates:
            print(f"⚠️  Found {len(duplicates)} symbols with multiple entries:")
            for symbol, count in sorted(duplicates.items())[:10]:
                print(f"   - {symbol}: {count} entries")
            if len(duplicates) > 10:
                print(f"   ... and {len(duplicates) - 10} more")
        else:
            print("   ✅ No duplicates found")
        
        print("\n" + "="*80)
        print("RESTORE COMPLETE")
        print("="*80)
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

