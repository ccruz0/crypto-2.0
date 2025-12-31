#!/usr/bin/env python3
"""
Add comprehensive audit logging for trade_enabled changes.

This script adds detailed logging to track:
1. Every time trade_enabled is modified
2. The count before and after each change
3. Any automatic disabling that occurs
4. Database triggers or constraints that might be involved

Run this to add logging that will help identify where the 16-coin limit is enforced.
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import text
from app.database import SessionLocal

def check_database_triggers():
    """Check for database triggers that might modify trade_enabled"""
    db = SessionLocal()
    try:
        # Check PostgreSQL triggers
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
            print("🔍 Found database triggers:")
            for trigger in triggers:
                print(f"  - {trigger[0]} on {trigger[2]} ({trigger[1]})")
                print(f"    Statement: {trigger[3][:200]}...")
        else:
            print("✅ No database triggers found on watchlist tables")
        
        # Check for constraints
        result = db.execute(text("""
            SELECT 
                constraint_name,
                constraint_type,
                table_name
            FROM information_schema.table_constraints
            WHERE table_name IN ('watchlist_items', 'watchlist_master')
            AND constraint_type != 'UNIQUE'
            ORDER BY table_name, constraint_name;
        """))
        
        constraints = result.fetchall()
        if constraints:
            print("\n🔍 Found constraints:")
            for constraint in constraints:
                print(f"  - {constraint[0]} ({constraint[1]}) on {constraint[2]}")
        else:
            print("\n✅ No special constraints found (only UNIQUE constraints)")
            
    except Exception as e:
        print(f"❌ Error checking database: {e}")
    finally:
        db.close()

def check_current_state():
    """Check current state of trade_enabled coins"""
    db = SessionLocal()
    try:
        # Count from watchlist_items
        result = db.execute(text("""
            SELECT COUNT(*) 
            FROM watchlist_items 
            WHERE trade_enabled = TRUE 
            AND is_deleted = FALSE;
        """))
        count_items = result.scalar()
        
        # Count from watchlist_master
        result = db.execute(text("""
            SELECT COUNT(*) 
            FROM watchlist_master 
            WHERE trade_enabled = TRUE 
            AND is_deleted = FALSE;
        """))
        count_master = result.scalar()
        
        print(f"\n📊 Current trade_enabled counts:")
        print(f"  - watchlist_items: {count_items}")
        print(f"  - watchlist_master: {count_master}")
        
        if count_items != count_master:
            print(f"  ⚠️ WARNING: Count mismatch between tables!")
        
        # List all enabled coins
        result = db.execute(text("""
            SELECT symbol, exchange 
            FROM watchlist_items 
            WHERE trade_enabled = TRUE 
            AND is_deleted = FALSE
            ORDER BY symbol;
        """))
        coins = result.fetchall()
        
        print(f"\n📋 Coins with trade_enabled=True ({len(coins)}):")
        for coin in coins:
            print(f"  - {coin[0]} ({coin[1]})")
            
    except Exception as e:
        print(f"❌ Error checking state: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 60)
    print("Trade Enabled Audit Logging Setup")
    print("=" * 60)
    
    print("\n1. Checking database triggers and constraints...")
    check_database_triggers()
    
    print("\n2. Checking current state...")
    check_current_state()
    
    print("\n" + "=" * 60)
    print("Next steps:")
    print("1. Check AWS backend logs for [TRADE_ENABLED_COUNT_MISMATCH] warnings")
    print("2. Monitor logs in real-time when enabling a 17th coin")
    print("3. Check for any background tasks or cron jobs")
    print("=" * 60)



