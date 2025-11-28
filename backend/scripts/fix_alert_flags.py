#!/usr/bin/env python3
"""
One-off script to ensure all alert-enabled watchlist rows also have buy/sell flags enabled.
"""
from collections import defaultdict

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem


def fix_alert_flags() -> None:
    session = SessionLocal()
    updated = 0
    per_symbol = defaultdict(int)
    try:
        items = session.query(WatchlistItem).all()
        for item in items:
            alert_enabled = bool(getattr(item, "alert_enabled", False))
            has_buy = bool(getattr(item, "buy_alert_enabled", False))
            has_sell = bool(getattr(item, "sell_alert_enabled", False))
            if alert_enabled and (not has_buy or not has_sell):
                if hasattr(item, "buy_alert_enabled"):
                    item.buy_alert_enabled = True
                if hasattr(item, "sell_alert_enabled"):
                    item.sell_alert_enabled = True
                per_symbol[getattr(item, "symbol", "UNKNOWN")] += 1
                updated += 1
        if updated:
            session.commit()
        else:
            session.rollback()
    finally:
        session.close()

    if updated:
        print(f"✅ Updated {updated} watchlist rows:")
        for symbol, count in sorted(per_symbol.items()):
            print(f"   • {symbol}: {count} row(s)")
    else:
        print("ℹ️  No rows required updates.")


if __name__ == "__main__":
    fix_alert_flags()

