#!/bin/bash
# Fix TON_USDT trade_enabled and trade_amount_usd in database

echo "=========================================="
echo "Fixing TON_USDT trade configuration"
echo "=========================================="

ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec -T backend-aws python << EOF
import sys
sys.path.insert(0, "/app")
from app.database import SessionLocal
from app.models.watchlist import WatchlistItem

db = SessionLocal()
try:
    item = db.query(WatchlistItem).filter(WatchlistItem.symbol == "TON_USDT").first()
    if item:
        print(f"Current state:")
        print(f"  trade_enabled: {item.trade_enabled}")
        print(f"  trade_amount_usd: {item.trade_amount_usd}")
        print(f"  alert_enabled: {item.alert_enabled}")
        print(f"  buy_alert_enabled: {item.buy_alert_enabled}")
        
        print(f"\nUpdating to:")
        print(f"  trade_enabled: True")
        print(f"  trade_amount_usd: 10.0")
        
        item.trade_enabled = True
        item.trade_amount_usd = 10.0
        
        db.commit()
        db.refresh(item)
        
        print(f"\n✅ Updated successfully!")
        print(f"New state:")
        print(f"  trade_enabled: {item.trade_enabled}")
        print(f"  trade_amount_usd: {item.trade_amount_usd}")
    else:
        print("❌ TON_USDT not found in database")
finally:
    db.close()
EOF
'

echo ""
echo "=========================================="
echo "Fix complete!"
echo "=========================================="

