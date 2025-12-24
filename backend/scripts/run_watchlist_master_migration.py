#!/usr/bin/env python3
"""
Run watchlist_master table migration.

This script handles both SQLite and PostgreSQL databases.
"""

import sys
import os
import logging
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.database import engine, Base
from sqlalchemy import text, inspect
from app.models.watchlist_master import WatchlistMaster
import sqlalchemy

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def check_table_exists(engine, table_name):
    """Check if a table exists."""
    inspector = inspect(engine)
    return table_name in inspector.get_table_names()


def get_table_columns(engine, table_name):
    """Get list of columns in a table."""
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return []
    columns = inspector.get_columns(table_name)
    return [col['name'] for col in columns]


def run_sqlite_migration(engine):
    """Run migration for SQLite database."""
    log.info("Running SQLite migration...")
    
    with engine.connect() as conn:
        # First, create the table if it doesn't exist
        if not check_table_exists(engine, "watchlist_master"):
            log.info("Creating watchlist_master table...")
            # Use SQLAlchemy to create table
            Base.metadata.create_all(engine, tables=[WatchlistMaster.__table__])
            log.info("✅ Created watchlist_master table")
        else:
            log.info("watchlist_master table already exists")
        
        # Migrate data from watchlist_items if it exists
        if check_table_exists(engine, "watchlist_items"):
            log.info("Migrating data from watchlist_items...")
            
            # Get columns from watchlist_items
            watchlist_columns = get_table_columns(engine, "watchlist_items")
            log.info(f"watchlist_items columns: {watchlist_columns[:10]}...")
            
            # Build INSERT statement with only columns that exist
            base_columns = [
                "symbol", "exchange", "is_deleted",
                "buy_target", "take_profit", "stop_loss",
                "trade_enabled", "trade_amount_usd", "trade_on_margin",
                "alert_enabled", "buy_alert_enabled", "sell_alert_enabled",
                "sl_tp_mode", "min_price_change_pct", "alert_cooldown_minutes",
                "sl_percentage", "tp_percentage", "sl_price", "tp_price",
                "notes", "signals", "skip_sl_tp_reminder",
                "price", "rsi", "atr", "ma50", "ma200", "ema10", "res_up", "res_down",
                "order_status", "order_date", "purchase_price", "quantity", "sold", "sell_price",
                "created_at"
            ]
            
            # Only include columns that exist in watchlist_items
            available_columns = [col for col in base_columns if col in watchlist_columns]
            
            # Add updated_at if it exists
            if "updated_at" in watchlist_columns:
                available_columns.append("updated_at")
            
            # Build SELECT statement (exclude updated_at from source, always use datetime('now'))
            select_parts = []
            target_columns = []
            
            for col in available_columns:
                if col == "updated_at":
                    # Skip updated_at from source, we'll add it separately
                    continue
                    
                target_columns.append(col)
                
                if col == "symbol":
                    select_parts.append("UPPER(symbol) as symbol")
                elif col == "exchange":
                    select_parts.append(f"COALESCE(exchange, 'CRYPTO_COM') as exchange")
                elif col in ["is_deleted", "trade_enabled", "trade_on_margin", "alert_enabled", 
                            "buy_alert_enabled", "sell_alert_enabled", "sold", "skip_sl_tp_reminder"]:
                    select_parts.append(f"COALESCE({col}, 0) as {col}")
                elif col == "sl_tp_mode":
                    select_parts.append(f"COALESCE({col}, 'conservative') as {col}")
                elif col == "order_status":
                    select_parts.append(f"COALESCE({col}, 'PENDING') as {col}")
                elif col == "created_at":
                    select_parts.append(f"COALESCE({col}, datetime('now')) as {col}")
                else:
                    select_parts.append(col)
            
            # Always add updated_at with current timestamp
            target_columns.append("updated_at")
            select_parts.append("datetime('now') as updated_at")
            
            # Build INSERT statement
            insert_sql = f"""
            INSERT OR IGNORE INTO watchlist_master ({', '.join(target_columns)})
            SELECT {', '.join(select_parts)}
            FROM watchlist_items
            WHERE is_deleted = 0 OR is_deleted IS NULL
            """
            
            try:
                result = conn.execute(text(insert_sql))
                conn.commit()
                migrated_count = result.rowcount
                log.info(f"✅ Migrated {migrated_count} rows from watchlist_items")
            except Exception as e:
                log.warning(f"Data migration warning: {e}")
                # Continue anyway - table is created, data will be seeded on first API call
        
        # Enrich with MarketData if available
        if check_table_exists(engine, "market_data"):
            log.info("Enriching with MarketData...")
            try:
                update_sql = """
                UPDATE watchlist_master
                SET 
                    price = COALESCE((SELECT price FROM market_data WHERE market_data.symbol = watchlist_master.symbol), price),
                    rsi = COALESCE((SELECT rsi FROM market_data WHERE market_data.symbol = watchlist_master.symbol), rsi),
                    atr = COALESCE((SELECT atr FROM market_data WHERE market_data.symbol = watchlist_master.symbol), atr),
                    ma50 = COALESCE((SELECT ma50 FROM market_data WHERE market_data.symbol = watchlist_master.symbol), ma50),
                    ma200 = COALESCE((SELECT ma200 FROM market_data WHERE market_data.symbol = watchlist_master.symbol), ma200),
                    ema10 = COALESCE((SELECT ema10 FROM market_data WHERE market_data.symbol = watchlist_master.symbol), ema10),
                    res_up = COALESCE((SELECT res_up FROM market_data WHERE market_data.symbol = watchlist_master.symbol), res_up),
                    res_down = COALESCE((SELECT res_down FROM market_data WHERE market_data.symbol = watchlist_master.symbol), res_down)
                WHERE EXISTS (SELECT 1 FROM market_data WHERE market_data.symbol = watchlist_master.symbol)
                """
                result = conn.execute(text(update_sql))
                conn.commit()
                log.info(f"✅ Enriched rows with MarketData")
            except Exception as e:
                log.warning(f"MarketData enrichment warning: {e}")
        
        log.info("✅ SQLite migration completed")
        return True


def run_postgresql_migration(engine):
    """Run migration for PostgreSQL database."""
    log.info("Running PostgreSQL migration...")
    
    # For PostgreSQL, we'll use SQLAlchemy to create the table
    # This is safer than raw SQL for cross-database compatibility
    
    try:
        # Check if table exists
        if check_table_exists(engine, "watchlist_master"):
            log.info("watchlist_master table already exists, skipping creation")
        else:
            # Create table using SQLAlchemy
            Base.metadata.create_all(engine, tables=[WatchlistMaster.__table__])
            log.info("✅ Created watchlist_master table")
        
        # Migrate data from watchlist_items
        with engine.connect() as conn:
            # Check if watchlist_items table exists
            if not check_table_exists(engine, "watchlist_items"):
                log.warning("watchlist_items table not found, skipping data migration")
                return True
            
            # Count existing rows in master table
            result = conn.execute(text("SELECT COUNT(*) FROM watchlist_master"))
            existing_count = result.scalar()
            
            if existing_count > 0:
                log.info(f"watchlist_master already has {existing_count} rows, skipping data migration")
                return True
            
            # Migrate data
            log.info("Migrating data from watchlist_items to watchlist_master...")
            
            # Insert from watchlist_items
            insert_sql = """
            INSERT INTO watchlist_master (
                symbol, exchange, is_deleted,
                buy_target, take_profit, stop_loss,
                trade_enabled, trade_amount_usd, trade_on_margin,
                alert_enabled, buy_alert_enabled, sell_alert_enabled,
                sl_tp_mode, min_price_change_pct, alert_cooldown_minutes,
                sl_percentage, tp_percentage, sl_price, tp_price,
                notes, signals, skip_sl_tp_reminder,
                price, rsi, atr, ma50, ma200, ema10, res_up, res_down,
                order_status, order_date, purchase_price, quantity, sold, sell_price,
                created_at, updated_at
            )
            SELECT 
                UPPER(symbol), COALESCE(exchange, 'CRYPTO_COM'), COALESCE(is_deleted, false),
                buy_target, take_profit, stop_loss,
                COALESCE(trade_enabled, false), trade_amount_usd, COALESCE(trade_on_margin, false),
                COALESCE(alert_enabled, false), 
                COALESCE(buy_alert_enabled, false), 
                COALESCE(sell_alert_enabled, false),
                COALESCE(sl_tp_mode, 'conservative'), min_price_change_pct, alert_cooldown_minutes,
                sl_percentage, tp_percentage, sl_price, tp_price,
                notes, signals, COALESCE(skip_sl_tp_reminder, false),
                price, rsi, atr, ma50, ma200, ema10, res_up, res_down,
                COALESCE(order_status, 'PENDING'), order_date, purchase_price, quantity, 
                COALESCE(sold, false), sell_price,
                COALESCE(created_at, NOW()), 
                COALESCE(updated_at, NOW())
            FROM watchlist_items
            WHERE is_deleted = false OR is_deleted IS NULL
            ON CONFLICT (symbol, exchange) DO NOTHING
            """
            
            result = conn.execute(text(insert_sql))
            conn.commit()
            migrated_count = result.rowcount
            log.info(f"✅ Migrated {migrated_count} rows from watchlist_items to watchlist_master")
            
            # Enrich with MarketData if available
            if check_table_exists(engine, "market_data"):
                log.info("Enriching with MarketData...")
                update_sql = """
                UPDATE watchlist_master
                SET 
                    price = COALESCE((SELECT price FROM market_data WHERE market_data.symbol = watchlist_master.symbol), price),
                    rsi = COALESCE((SELECT rsi FROM market_data WHERE market_data.symbol = watchlist_master.symbol), rsi),
                    atr = COALESCE((SELECT atr FROM market_data WHERE market_data.symbol = watchlist_master.symbol), atr),
                    ma50 = COALESCE((SELECT ma50 FROM market_data WHERE market_data.symbol = watchlist_master.symbol), ma50),
                    ma200 = COALESCE((SELECT ma200 FROM market_data WHERE market_data.symbol = watchlist_master.symbol), ma200),
                    ema10 = COALESCE((SELECT ema10 FROM market_data WHERE market_data.symbol = watchlist_master.symbol), ema10),
                    res_up = COALESCE((SELECT res_up FROM market_data WHERE market_data.symbol = watchlist_master.symbol), res_up),
                    res_down = COALESCE((SELECT res_down FROM market_data WHERE market_data.symbol = watchlist_master.symbol), res_down),
                    volume_ratio = COALESCE((SELECT volume_ratio FROM market_data WHERE market_data.symbol = watchlist_master.symbol), volume_ratio),
                    current_volume = COALESCE((SELECT current_volume FROM market_data WHERE market_data.symbol = watchlist_master.symbol), current_volume),
                    avg_volume = COALESCE((SELECT avg_volume FROM market_data WHERE market_data.symbol = watchlist_master.symbol), avg_volume),
                    volume_24h = COALESCE((SELECT volume_24h FROM market_data WHERE market_data.symbol = watchlist_master.symbol), volume_24h)
                WHERE EXISTS (SELECT 1 FROM market_data WHERE market_data.symbol = watchlist_master.symbol)
                """
                result = conn.execute(text(update_sql))
                conn.commit()
                log.info(f"✅ Enriched {result.rowcount} rows with MarketData")
        
        log.info("✅ PostgreSQL migration completed")
        return True
        
    except Exception as e:
        log.error(f"Error in PostgreSQL migration: {e}", exc_info=True)
        return False


def main():
    """Main migration function."""
    log.info("=" * 60)
    log.info("Watchlist Master Table Migration")
    log.info("=" * 60)
    
    # Determine database type
    database_url = str(engine.url)
    is_sqlite = database_url.startswith("sqlite")
    is_postgres = "postgresql" in database_url or "postgres" in database_url
    
    log.info(f"Database URL: {database_url.split('@')[-1] if '@' in database_url else database_url}")
    log.info(f"Database type: {'SQLite' if is_sqlite else 'PostgreSQL' if is_postgres else 'Unknown'}")
    
    try:
        if is_sqlite:
            success = run_sqlite_migration(engine)
        elif is_postgres:
            success = run_postgresql_migration(engine)
        else:
            log.error("Unknown database type. Only SQLite and PostgreSQL are supported.")
            return 1
        
        if success:
            log.info("=" * 60)
            log.info("✅ Migration completed successfully!")
            log.info("=" * 60)
            
            # Verify table exists
            if check_table_exists(engine, "watchlist_master"):
                with engine.connect() as conn:
                    result = conn.execute(text("SELECT COUNT(*) FROM watchlist_master"))
                    count = result.scalar()
                    log.info(f"✅ Verified: watchlist_master table exists with {count} rows")
            else:
                log.error("❌ Migration may have failed: watchlist_master table not found")
                return 1
            
            return 0
        else:
            log.error("❌ Migration failed")
            return 1
            
    except Exception as e:
        log.error(f"❌ Migration error: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())

