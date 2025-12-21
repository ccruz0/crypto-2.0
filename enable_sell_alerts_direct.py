#!/usr/bin/env python3
"""Direct SQL update to enable sell alerts - can be run via SSM"""
import sys
sys.path.insert(0, '/app')
from sqlalchemy.orm import Session
from sqlalchemy import text
from app.database import SessionLocal

db = SessionLocal()
try:
    result = db.execute(text("""
        UPDATE watchlist_items 
        SET sell_alert_enabled = TRUE 
        WHERE alert_enabled = TRUE 
          AND (sell_alert_enabled IS NULL OR sell_alert_enabled = FALSE)
    """))
    db.commit()
    count = result.rowcount
    print(f"✅ Enabled sell alerts for {count} symbols")
    
    result2 = db.execute(text("""
        SELECT COUNT(*) 
        FROM watchlist_items 
        WHERE alert_enabled = TRUE AND sell_alert_enabled = TRUE
    """))
    total = result2.scalar()
    print(f"📊 Total symbols with sell alerts enabled: {total}")
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    db.rollback()
    sys.exit(1)
finally:
    db.close()




