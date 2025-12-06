#!/usr/bin/env python3
"""
Cleanup script to remove duplicate watchlist entries.
Keeps the most recently updated record for each symbol and deletes the rest.
"""
import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from sqlalchemy import func

def cleanup_duplicates():
    """Remove duplicate watchlist entries, keeping only the most recent one per symbol"""
    db = SessionLocal()
    try:
        # Find duplicates grouped by symbol
        duplicates_query = db.query(
            WatchlistItem.symbol,
            func.count(WatchlistItem.id).label('count')
        ).group_by(WatchlistItem.symbol).having(func.count(WatchlistItem.id) > 1).all()
        
        if not duplicates_query:
            print("✅ No duplicates found")
            return
        
        print(f"Found {len(duplicates_query)} symbols with duplicates:")
        total_deleted = 0
        
        for dup in duplicates_query:
            symbol = dup.symbol
            count = dup.count
            print(f"\n📊 {symbol}: {count} entries")
            
            # Get all entries for this symbol, ordered by updated_at desc (most recent first)
            # If updated_at is None, use created_at
            entries = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).order_by(
                WatchlistItem.created_at.desc()
            ).all()
            
            if len(entries) <= 1:
                continue
            
            # Keep the first (most recent) entry
            keep_entry = entries[0]
            delete_entries = entries[1:]
            
            print(f"  ✅ Keeping entry ID {keep_entry.id} (created: {keep_entry.created_at})")
            print(f"  🗑️  Deleting {len(delete_entries)} duplicate(s):")
            
            for entry in delete_entries:
                print(f"     - ID {entry.id} (created: {entry.created_at})")
                db.delete(entry)
                total_deleted += 1
        
        db.commit()
        print(f"\n✅ Cleanup complete: Deleted {total_deleted} duplicate entries")
        
    except Exception as e:
        print(f"❌ Error during cleanup: {e}")
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    cleanup_duplicates()

