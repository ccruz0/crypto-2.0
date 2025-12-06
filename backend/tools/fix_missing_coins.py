#!/usr/bin/env python3
"""
Fix missing coins from dashboard by checking and restoring deleted items.
"""
import sys
sys.path.insert(0, '/app')

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def main():
    db = SessionLocal()
    
    try:
        print("="*80)
        print("FIXING MISSING COINS FROM DASHBOARD")
        print("="*80)
        
        # Check SOL_USDT
        print("\n1. CHECKING SOL_USDT:")
        print("-"*80)
        sol_items = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == "SOL_USDT"
        ).all()
        
        if not sol_items:
            print("❌ SOL_USDT NOT FOUND - creating new entry")
            # Create new entry
            new_sol = WatchlistItem(
                symbol="SOL_USDT",
                exchange="CRYPTO_COM",
                is_deleted=False,
                alert_enabled=True,
                trade_enabled=True,
                trade_amount_usd=10.0
            )
            db.add(new_sol)
            db.commit()
            print("✅ Created new SOL_USDT entry")
        else:
            print(f"Found {len(sol_items)} SOL_USDT entry/entries:")
            restored = False
            for item in sol_items:
                print(f"   - ID: {item.id}, is_deleted: {item.is_deleted}")
                if item.is_deleted:
                    print(f"     → Restoring (setting is_deleted=False)")
                    item.is_deleted = False
                    restored = True
            if restored:
                db.commit()
                print("✅ Restored SOL_USDT")
        
        # Check for other common coins that might be deleted
        print("\n2. CHECKING OTHER COMMON COINS:")
        print("-"*80)
        common_symbols = ["BTC_USDT", "ETH_USDT", "DOGE_USDT", "ADA_USDT", "TON_USDT", "LDO_USDT"]
        
        for symbol in common_symbols:
            items = db.query(WatchlistItem).filter(
                WatchlistItem.symbol == symbol
            ).all()
            
            if not items:
                print(f"⚠️  {symbol} NOT FOUND")
            else:
                deleted_count = sum(1 for item in items if item.is_deleted)
                if deleted_count > 0:
                    print(f"⚠️  {symbol}: {deleted_count} deleted entry/entries")
                    # Restore the most recent one
                    for item in sorted(items, key=lambda x: x.created_at or 0, reverse=True):
                        if item.is_deleted:
                            print(f"     → Restoring ID {item.id}")
                            item.is_deleted = False
                            db.commit()
                            break
        
        # Show summary
        print("\n3. SUMMARY:")
        print("-"*80)
        all_items = db.query(WatchlistItem).filter(
            WatchlistItem.is_deleted == False
        ).all()
        print(f"✅ Total non-deleted items: {len(all_items)}")
        print(f"\nFirst 20 symbols:")
        for item in all_items[:20]:
            print(f"   - {item.symbol}")
        
        print("\n" + "="*80)
        print("FIX COMPLETE")
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

