#!/usr/bin/env python3
"""
Script to fix old blocked portfolio alerts in the database.

This script updates old "ALERTA BLOQUEADA POR VALOR EN CARTERA" messages
to mark them as order_skipped=True and blocked=False, since these were
actually order blocks, not alert blocks.

Usage:
    docker compose exec backend python scripts/fix_blocked_portfolio_alerts.py
    OR
    docker compose --profile aws exec backend-aws python scripts/fix_blocked_portfolio_alerts.py
"""
import sys
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent
sys.path.insert(0, str(backend_path))

from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from sqlalchemy import and_

def fix_blocked_portfolio_alerts():
    """Update old portfolio alert blocks to order_skipped"""
    db = SessionLocal()
    try:
        # Find messages with the old blocked portfolio alert pattern
        old_messages = db.query(TelegramMessage).filter(
            and_(
                TelegramMessage.blocked == True,
                TelegramMessage.message.like('%ALERTA BLOQUEADA POR VALOR EN CARTERA%')
            )
        ).all()
        
        print(f"Found {len(old_messages)} old blocked portfolio alert messages")
        
        if len(old_messages) == 0:
            print("✅ No old blocked portfolio alerts found. Database is clean.")
            return
        
        # Update each message
        updated_count = 0
        for msg in old_messages:
            # These were actually order blocks, not alert blocks
            # Update to reflect that orders were skipped, but alerts should have been sent
            msg.blocked = False
            msg.order_skipped = True
            # Update message to reflect the correct status
            if "ALERTA BLOQUEADA" in msg.message:
                msg.message = msg.message.replace(
                    "🚫 ALERTA BLOQUEADA POR VALOR EN CARTERA",
                    "⚠️ ORDEN NO EJECUTADA POR VALOR EN CARTERA"
                )
            updated_count += 1
            print(f"  - Updated message ID {msg.id} for {msg.symbol}")
        
        # Commit changes
        db.commit()
        print(f"\n✅ Successfully updated {updated_count} messages")
        print("   - blocked: True → False")
        print("   - order_skipped: None/False → True")
        print("   - Message text updated to reflect order skip (not alert block)")
        
    except Exception as e:
        print(f"❌ Error fixing blocked portfolio alerts: {e}")
        import traceback
        traceback.print_exc()
        db.rollback()
        raise
    finally:
        db.close()

if __name__ == "__main__":
    print("=" * 80)
    print("Fixing old blocked portfolio alerts in database")
    print("=" * 80)
    fix_blocked_portfolio_alerts()
    print("=" * 80)
    print("Done!")


