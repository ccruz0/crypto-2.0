#!/usr/bin/env python3
"""Script to add ATOM_USDT to watchlist and enable sell_alert_enabled"""
import sys
import os

# Add backend to path if running from project root
backend_path = os.path.join(os.path.dirname(__file__), 'backend')
if os.path.exists(backend_path):
    sys.path.insert(0, backend_path)

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

def enable_atom_sell_alert():
    """Add ATOM_USDT to watchlist and enable sell_alert_enabled"""
    db = SessionLocal()
    try:
        # Find ATOM_USDT in watchlist (including soft-deleted)
        atom_item = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == "ATOM_USDT"
        ).first()
        
        if atom_item:
            # Item exists - check if it's soft-deleted
            if atom_item.is_deleted:
                print("📝 ATOM_USDT exists but is soft-deleted. Restoring...")
                atom_item.is_deleted = False
            else:
                print("✅ ATOM_USDT already exists in watchlist")
        else:
            # Create new watchlist item
            print("➕ Adding ATOM_USDT to watchlist...")
            atom_item = WatchlistItem(
                symbol="ATOM_USDT",
                exchange="CRYPTO_COM",  # Default exchange
                alert_enabled=True,
                buy_alert_enabled=True,
                sell_alert_enabled=True,
                is_deleted=False,
                sl_tp_mode="conservative"
            )
            db.add(atom_item)
        
        # Ensure all alert flags are enabled
        atom_item.alert_enabled = True
        atom_item.buy_alert_enabled = True
        atom_item.sell_alert_enabled = True
        
        db.commit()
        
        print("\n✅ Successfully configured ATOM_USDT:")
        print(f"   Symbol: {atom_item.symbol}")
        print(f"   Exchange: {atom_item.exchange}")
        print(f"   alert_enabled: {atom_item.alert_enabled}")
        print(f"   buy_alert_enabled: {atom_item.buy_alert_enabled}")
        print(f"   sell_alert_enabled: {atom_item.sell_alert_enabled}")
        print(f"   is_deleted: {atom_item.is_deleted}")
        
        print("\n💡 ATOM_USDT will now send SELL alerts when:")
        print("   - RSI > 70 (overbought condition)")
        print("   - Price breaks below MA10w with high volume")
        print("   - Alert cooldown period has passed (5 minutes default)")
        print("   - Minimum price change % threshold is met (1.0% default)")
        print("\n📊 The system will monitor ATOM_USDT and send alerts via Telegram")
        print("   when SELL conditions are met.")
        
    except Exception as e:
        print(f"❌ Error: {e}", file=sys.stderr)
        db.rollback()
        import traceback
        traceback.print_exc()
    finally:
        db.close()

if __name__ == "__main__":
    enable_atom_sell_alert()

