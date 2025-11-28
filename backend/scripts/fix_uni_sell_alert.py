#!/usr/bin/env python3
"""Fix UNI sell_alert_enabled and add missing columns if needed"""
from app.database import SessionLocal, engine
from sqlalchemy import text
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    # Check if columns exist and add them if needed
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
    
    # Check UNI configuration
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == "UNI_USD").first()
    if item:
        print(f"\nUNI_USD current configuration:")
        print(f"  sell_alert_enabled: {getattr(item, 'sell_alert_enabled', 'NOT SET')}")
        print(f"  buy_alert_enabled: {getattr(item, 'buy_alert_enabled', 'NOT SET')}")
        print(f"  trade_enabled: {item.trade_enabled}")
        
        # Enable sell alerts
        item.sell_alert_enabled = True
        db.commit()
        print(f"\n✅ Updated UNI_USD: sell_alert_enabled = {item.sell_alert_enabled}")
    else:
        print("❌ UNI_USD not found in watchlist")
finally:
    db.close()


