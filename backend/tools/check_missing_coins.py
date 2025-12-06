#!/usr/bin/env python3
"""
Check why coins are missing from the dashboard.
Verifies is_deleted flag and other filters.
"""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def main():
    db = SessionLocal()
    
    try:
        print("="*80)
        print("CHECKING MISSING COINS FROM DASHBOARD")
        print("="*80)
        
        # Check SOL_USDT specifically
        print("\n1. CHECKING SOL_USDT:")
        print("-"*80)
        sol_items = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == "SOL_USDT"
        ).all()
        
        if not sol_items:
            print("❌ SOL_USDT NOT FOUND in database at all!")
        else:
            print(f"✅ Found {len(sol_items)} SOL_USDT entry/entries:")
            for item in sol_items:
                print(f"   - ID: {item.id}")
                print(f"     is_deleted: {item.is_deleted}")
                print(f"     created_at: {item.created_at}")
                print(f"     trade_enabled: {item.trade_enabled}")
                print(f"     alert_enabled: {item.alert_enabled}")
                print(f"     price: {item.price}")
        
        # Check all deleted items
        print("\n2. CHECKING ALL DELETED ITEMS:")
        print("-"*80)
        deleted_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == True
        ).all()
        
        print(f"Found {len(deleted_items)} deleted items:")
        for item in deleted_items[:20]:  # Show first 20
            print(f"   - {item.symbol} (ID: {item.id}, created: {item.created_at})")
        
        if len(deleted_items) > 20:
            print(f"   ... and {len(deleted_items) - 20} more")
        
        # Check all non-deleted items
        print("\n3. CHECKING ALL NON-DELETED ITEMS:")
        print("-"*80)
        non_deleted = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).order_by(WatchlistItem.created_at.desc()).all()
        
        print(f"Found {len(non_deleted)} non-deleted items:")
        
        # Check for duplicates
        symbols_seen = {}
        duplicates = []
        for item in non_deleted:
            if item.symbol in symbols_seen:
                duplicates.append(item.symbol)
            else:
                symbols_seen[item.symbol] = item
        
        if duplicates:
            print(f"\n⚠️  Found {len(set(duplicates))} symbols with duplicates:")
            for symbol in set(duplicates):
                count = len([i for i in non_deleted if i.symbol == symbol])
                print(f"   - {symbol}: {count} entries")
        
        # Show first 30 symbols
        print(f"\nFirst 30 non-deleted symbols:")
        for item in non_deleted[:30]:
            print(f"   - {item.symbol} (ID: {item.id}, created: {item.created_at})")
        
        if len(non_deleted) > 30:
            print(f"   ... and {len(non_deleted) - 30} more")
        
        # Check if SOL_USDT is in non-deleted list
        print("\n4. CHECKING IF SOL_USDT SHOULD APPEAR:")
        print("-"*80)
        sol_non_deleted = [item for item in non_deleted if item.symbol == "SOL_USDT"]
        
        if sol_non_deleted:
            print(f"✅ SOL_USDT IS in non-deleted list (should appear in dashboard)")
            for item in sol_non_deleted:
                print(f"   - ID: {item.id}, created_at: {item.created_at}")
        else:
            print("❌ SOL_USDT is NOT in non-deleted list (will NOT appear in dashboard)")
            print("   → Check if is_deleted=True or if there's a database issue")
        
        # Check limit issue (dashboard limits to 100)
        print("\n5. CHECKING LIMIT ISSUE:")
        print("-"*80)
        if len(non_deleted) > 100:
            print(f"⚠️  WARNING: {len(non_deleted)} non-deleted items, but dashboard limits to 100")
            print(f"   → Items beyond the 100 limit will not appear")
            print(f"\n   Items that might be cut off:")
            for item in non_deleted[100:110]:
                print(f"   - {item.symbol} (created: {item.created_at})")
        else:
            print(f"✅ {len(non_deleted)} non-deleted items (within 100 limit)")
        
        print("\n" + "="*80)
        print("DIAGNOSTIC COMPLETE")
        print("="*80)
        
        # Recommendations
        print("\nRECOMMENDATIONS:")
        if sol_items and all(item.is_deleted for item in sol_items):
            print("1. SOL_USDT is marked as deleted - restore it:")
            print("   UPDATE watchlist_items SET is_deleted = FALSE WHERE symbol = 'SOL_USDT';")
        elif len(non_deleted) > 100:
            print("1. Too many items - consider increasing limit or cleaning up old entries")
        elif sol_non_deleted:
            print("1. SOL_USDT should appear - check frontend filters or API response")
        
        return 0
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
    finally:
        db.close()

if __name__ == '__main__':
    sys.exit(main())

