#!/usr/bin/env python3
"""
Set trade_amount_usd for a watchlist symbol directly in the database.

Use when automatic order creation fails with "Amount USD not configured".
Runs inside the backend container (no API/auth needed).

Usage:
  python scripts/set_watchlist_trade_amount.py BTC_USD 50
  python scripts/set_watchlist_trade_amount.py BTC_USD 50 --exchange CRYPTO_COM

Via Docker:
  docker compose --profile aws exec backend-aws python scripts/set_watchlist_trade_amount.py BTC_USD 50
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.database import SessionLocal
from app.models.watchlist import WatchlistItem
from app.models.watchlist_master import WatchlistMaster


def set_trade_amount(symbol: str, amount_usd: float, exchange: str = "CRYPTO_COM") -> bool:
    """Update trade_amount_usd for symbol in watchlist_items and watchlist_master."""
    symbol = symbol.upper().strip()
    exchange = (exchange or "CRYPTO_COM").upper().strip()
    if amount_usd <= 0:
        print(f"Error: amount_usd must be positive, got {amount_usd}")
        return False

    db = SessionLocal()
    try:
        # Update watchlist_items
        items = db.query(WatchlistItem).filter(
            WatchlistItem.symbol == symbol,
            WatchlistItem.exchange == exchange,
        ).all()
        if hasattr(WatchlistItem, "is_deleted"):
            items = [i for i in items if not getattr(i, "is_deleted", False)]

        # Update watchlist_master
        masters = db.query(WatchlistMaster).filter(
            WatchlistMaster.symbol == symbol,
            WatchlistMaster.exchange == exchange,
        ).all()
        if hasattr(WatchlistMaster, "is_deleted"):
            masters = [m for m in masters if not getattr(m, "is_deleted", False)]

        updated_items = 0
        for item in items:
            item.trade_amount_usd = amount_usd
            updated_items += 1

        updated_masters = 0
        for master in masters:
            master.trade_amount_usd = amount_usd
            updated_masters += 1

        db.commit()

        if updated_items == 0 and updated_masters == 0:
            print(f"Warning: No watchlist entry found for {symbol} ({exchange})")
            return False

        print(f"OK: Set trade_amount_usd=${amount_usd} for {symbol}")
        if updated_items:
            print(f"  - watchlist_items: {updated_items} row(s)")
        if updated_masters:
            print(f"  - watchlist_master: {updated_masters} row(s)")
        return True
    except Exception as e:
        db.rollback()
        print(f"Error: {e}")
        return False
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Set trade_amount_usd for a symbol in the watchlist")
    parser.add_argument("symbol", help="Trading symbol (e.g. BTC_USD)")
    parser.add_argument("amount", type=float, help="Trade amount in USD")
    parser.add_argument("--exchange", default="CRYPTO_COM", help="Exchange (default: CRYPTO_COM)")
    args = parser.parse_args()
    ok = set_trade_amount(args.symbol, args.amount, args.exchange)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
