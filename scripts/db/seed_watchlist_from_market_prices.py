#!/usr/bin/env python3
"""Seed watchlist_items from distinct market_prices.symbol (missing symbols only). Safe to run multiple times."""
from app.database import engine
from sqlalchemy import text

def main():
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO watchlist_items (symbol, exchange, is_deleted, created_at, trade_enabled, alert_enabled)
            SELECT DISTINCT mp.symbol, 'crypto_com', false, now(), false, true
            FROM market_prices mp
            WHERE mp.symbol IS NOT NULL
            AND NOT EXISTS (
                SELECT 1 FROM watchlist_items wi
                WHERE wi.symbol = mp.symbol AND (wi.is_deleted = false OR wi.is_deleted IS NULL)
            )
        """))
    with engine.connect() as conn:
        r = conn.execute(text("SELECT COUNT(*) FROM watchlist_items"))
        print("watchlist_items count:", r.scalar())
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
