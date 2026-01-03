#!/usr/bin/env python3
"""
Quick verification script for watchlist_master table.

Checks:
1. Table exists
2. Has data
3. Field timestamps are working
4. Can update fields with timestamps
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine, get_db
from app.models.watchlist_master import WatchlistMaster
from sqlalchemy import text, inspect
from datetime import datetime, timezone

def verify_table():
    """Verify table exists and has data."""
    print("=" * 60)
    print("Verifying watchlist_master table")
    print("=" * 60)
    
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    
    if "watchlist_master" not in tables:
        print("❌ watchlist_master table does not exist")
        return False
    
    print("✅ watchlist_master table exists")
    
    # Check row count
    with engine.connect() as conn:
        result = conn.execute(text("SELECT COUNT(*) FROM watchlist_master"))
        count = result.scalar()
        print(f"✅ Table has {count} rows")
        
        if count == 0:
            print("⚠️  Warning: Table is empty (will be seeded on first API call)")
        else:
            # Check a sample row
            result = conn.execute(text("SELECT symbol, field_updated_at FROM watchlist_master LIMIT 1"))
            row = result.fetchone()
            if row:
                symbol, field_updated_at = row
                print(f"✅ Sample row: {symbol}")
                print(f"   field_updated_at: {field_updated_at[:100] if field_updated_at else 'None'}...")
    
    return True


def test_field_timestamps():
    """Test field timestamp functionality."""
    print("\n" + "=" * 60)
    print("Testing field timestamp functionality")
    print("=" * 60)
    
    db = next(get_db())
    
    try:
        # Get first item
        master = db.query(WatchlistMaster).first()
        
        if not master:
            print("⚠️  No rows in table to test")
            return False
        
        print(f"Testing with: {master.symbol}")
        
        # Test update_field
        old_price = master.price
        test_price = 50000.0 if old_price != 50000.0 else 50001.0
        
        master.update_field('price', test_price)
        db.commit()
        db.refresh(master)
        
        print(f"✅ Updated price: {old_price} → {test_price}")
        
        # Check timestamp
        last_updated = master.get_field_last_updated('price')
        if last_updated:
            print(f"✅ Field timestamp recorded: {last_updated.isoformat()}")
            
            # Check it's recent (within last minute)
            now = datetime.now(timezone.utc)
            seconds_ago = (now - last_updated).total_seconds()
            if seconds_ago < 60:
                print(f"✅ Timestamp is recent ({seconds_ago:.1f} seconds ago)")
            else:
                print(f"⚠️  Timestamp is old ({seconds_ago:.1f} seconds ago)")
        else:
            print("❌ Field timestamp not found")
            return False
        
        # Restore original price
        if old_price is not None:
            master.update_field('price', old_price)
            db.commit()
            print(f"✅ Restored original price: {old_price}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing field timestamps: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        return False
    finally:
        db.close()


def test_serialization():
    """Test that serialization includes field_updated_at."""
    print("\n" + "=" * 60)
    print("Testing serialization")
    print("=" * 60)
    
    try:
        from app.api.routes_dashboard import _serialize_watchlist_master
        
        db = next(get_db())
        master = db.query(WatchlistMaster).first()
        
        if not master:
            print("⚠️  No rows to test")
            return False
        
        serialized = _serialize_watchlist_master(master, db=db)
        
        if 'field_updated_at' in serialized:
            print("✅ Serialization includes field_updated_at")
            timestamps = serialized['field_updated_at']
            if timestamps:
                print(f"✅ Found {len(timestamps)} field timestamps")
                print(f"   Sample fields: {list(timestamps.keys())[:5]}")
            else:
                print("⚠️  field_updated_at is empty")
        else:
            print("❌ Serialization missing field_updated_at")
            return False
        
        db.close()
        return True
        
    except Exception as e:
        print(f"❌ Error testing serialization: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all verification checks."""
    print("\n" + "=" * 60)
    print("Watchlist Master Table Verification")
    print("=" * 60)
    
    results = []
    
    # Test 1: Table exists and has data
    success = verify_table()
    results.append(("Table verification", success))
    
    if success:
        # Test 2: Field timestamps
        success = test_field_timestamps()
        results.append(("Field timestamps", success))
        
        # Test 3: Serialization
        success = test_serialization()
        results.append(("Serialization", success))
    
    # Summary
    print("\n" + "=" * 60)
    print("Verification Summary")
    print("=" * 60)
    for test_name, success in results:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    all_passed = all(success for _, success in results)
    print("=" * 60)
    
    if all_passed:
        print("✅ All verifications passed!")
        print("\nNext steps:")
        print("1. Start backend server: uvicorn app.main:app --reload")
        print("2. Test endpoints: python3 scripts/test_watchlist_master_endpoints.py")
        return 0
    else:
        print("❌ Some verifications failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())














