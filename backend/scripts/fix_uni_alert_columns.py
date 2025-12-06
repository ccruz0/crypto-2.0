#!/usr/bin/env python3
"""Add alert columns and enable UNI sell alerts"""
import sys
import os
sys.path.insert(0, '/app')

from app.database import SessionLocal
from sqlalchemy import text
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    # Check if columns exist
    result = db.execute(text("""
        SELECT column_name 
        FROM information_schema.columns 
        WHERE table_name = 'watchlist_items' 
        AND column_name IN ('sell_alert_enabled', 'buy_alert_enabled')
    """))
    existing = [row[0] for row in result]
    print(f"Existing columns: {existing}")
    
    # Add missing columns
    if "sell_alert_enabled" not in existing:
        db.execute(text("ALTER TABLE watchlist_items ADD COLUMN sell_alert_enabled BOOLEAN DEFAULT FALSE"))
        print("✅ Added sell_alert_enabled column")
    if "buy_alert_enabled" not in existing:
        db.execute(text("ALTER TABLE watchlist_items ADD COLUMN buy_alert_enabled BOOLEAN DEFAULT FALSE"))
        print("✅ Added buy_alert_enabled column")
    
    db.commit()
    
    # Now update UNI
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == "UNI_USD").first()
    if item:
        item.sell_alert_enabled = True
        db.commit()
        db.refresh(item)
        print(f"✅ Updated UNI_USD:")
        print(f"   sell_alert_enabled = {item.sell_alert_enabled}")
        print(f"   buy_alert_enabled = {getattr(item, 'buy_alert_enabled', None)}")
    else:
        print("❌ UNI_USD not found in watchlist")
finally:
    db.close()


