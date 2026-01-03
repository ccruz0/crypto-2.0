#!/usr/bin/env python3
"""
Check for the 16-coin trade_enabled limit by querying the database directly.
This will help identify if there's a database-level constraint or trigger.
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text, inspect
from app.database import SessionLocal, engine
from app.models.watchlist import WatchlistItem
from app.models.watchlist_master import WatchlistMaster

def check_database_constraints():
    """Check for database-level constraints or triggers"""
    db = SessionLocal()
    try:
        # Check if we're using PostgreSQL or SQLite
        dialect = engine.dialect.name
        print(f"Database dialect: {dialect}")
        
        if dialect == 'postgresql':
            # Check for triggers
            result = db.execute(text("""
                SELECT 
                    trigger_name,
                    event_manipulation,
                    event_object_table,
                    action_statement
                FROM information_schema.triggers
                WHERE event_object_table IN ('watchlist_items', 'watchlist_master')
                ORDER BY event_object_table, trigger_name;
            """))
            
            triggers = result.fetchall()
            if triggers:
                print("\n🔍 Found database triggers:")
                for trigger in triggers:
                    print(f"  - {trigger[0]} on {trigger[2]} ({trigger[1]})")
                    print(f"    Statement: {trigger[3][:200]}...")
            else:
                print("\n✅ No database triggers found on watchlist tables")
            
            # Check for check constraints
            result = db.execute(text("""
                SELECT 
                    constraint_name,
                    constraint_type,
                    table_name,
                    check_clause
                FROM information_schema.table_constraints tc
                LEFT JOIN information_schema.check_constraints cc 
                    ON tc.constraint_name = cc.constraint_name
                WHERE tc.table_name IN ('watchlist_items', 'watchlist_master')
                AND tc.constraint_type = 'CHECK'
                ORDER BY table_name, constraint_name;
            """))
            
            constraints = result.fetchall()
            if constraints:
                print("\n🔍 Found CHECK constraints:")
                for constraint in constraints:
                    print(f"  - {constraint[0]} on {constraint[2]}")
                    if constraint[3]:
                        print(f"    Clause: {constraint[3]}")
            else:
                print("\n✅ No CHECK constraints found")
        
        # Check current counts
        items_count = db.query(WatchlistItem).filter(
            WatchlistItem.trade_enabled == True,
            WatchlistItem.is_deleted == False
        ).count()
        
        master_count = db.query(WatchlistMaster).filter(
            WatchlistMaster.trade_enabled == True,
            WatchlistMaster.is_deleted == False
        ).count()
        
        print(f"\n📊 Current trade_enabled counts:")
        print(f"  - watchlist_items: {items_count}")
        print(f"  - watchlist_master: {master_count}")
        
        if items_count != master_count:
            print(f"  ⚠️ WARNING: Count mismatch between tables!")
        
        # List all enabled coins from both tables
        items_enabled = db.query(WatchlistItem).filter(
            WatchlistItem.trade_enabled == True,
            WatchlistItem.is_deleted == False
        ).order_by(WatchlistItem.symbol).all()
        
        master_enabled = db.query(WatchlistMaster).filter(
            WatchlistMaster.trade_enabled == True,
            WatchlistMaster.is_deleted == False
        ).order_by(WatchlistMaster.symbol).all()
        
        items_symbols = {item.symbol for item in items_enabled}
        master_symbols = {item.symbol for item in master_enabled}
        
        print(f"\n📋 Coins with trade_enabled=True in watchlist_items ({len(items_symbols)}):")
        for symbol in sorted(items_symbols):
            print(f"  - {symbol}")
        
        print(f"\n📋 Coins with trade_enabled=True in watchlist_master ({len(master_symbols)}):")
        for symbol in sorted(master_symbols):
            print(f"  - {symbol}")
        
        # Check for mismatches
        only_in_items = items_symbols - master_symbols
        only_in_master = master_symbols - items_symbols
        
        if only_in_items:
            print(f"\n⚠️ Coins only in watchlist_items: {sorted(only_in_items)}")
        if only_in_master:
            print(f"\n⚠️ Coins only in watchlist_master: {sorted(only_in_master)}")
        
        # Check if count is exactly 16
        if items_count == 16:
            print(f"\n🔍 Count is exactly 16 - this might indicate a limit is being enforced")
        elif items_count > 16:
            print(f"\n✅ Count is {items_count} (more than 16) - no hard limit detected")
        else:
            print(f"\n📊 Count is {items_count} (less than 16)")
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Trade Enabled Limit Checker")
    print("=" * 60)
    check_database_constraints()
    print("=" * 60)





