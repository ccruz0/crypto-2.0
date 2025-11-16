-- Performance indexes for dashboard queries
-- This migration adds indexes to prevent /api/dashboard/state endpoint hangs
-- Created: 2025-11-03
-- 
-- Usage: Execute this script directly against your PostgreSQL database:
--   psql -U trader -d atp -f migrations/add_dashboard_indexes.sql
--   Or from Docker:
--   docker compose exec db psql -U trader -d atp -f /path/to/add_dashboard_indexes.sql

-- TradeSignal indexes for fast_signals query
-- Query: should_trade=true OR status IN (ORDER_PLACED, FILLED) ORDER BY last_update_at DESC
CREATE INDEX IF NOT EXISTS idx_tradesignal_should_trade_last_update 
  ON trade_signals (should_trade, last_update_at DESC)
  WHERE should_trade = true;

-- TradeSignal index for status filtering (without WHERE clause for enum compatibility)
CREATE INDEX IF NOT EXISTS idx_tradesignal_status_last_update 
  ON trade_signals (status, last_update_at DESC);

-- TradeSignal indexes for slow_signals query (simplified without WHERE clause)
CREATE INDEX IF NOT EXISTS idx_tradesignal_slow_query
  ON trade_signals (should_trade, status, last_update_at DESC);

-- TradeSignal composite index for symbol-based queries
CREATE INDEX IF NOT EXISTS idx_tradesignal_symbol_should_created
  ON trade_signals (symbol, should_trade, last_update_at DESC);

-- ExchangeOrder indexes for open_orders query
-- Query: status IN (NEW, ACTIVE, PARTIALLY_FILLED) ORDER BY exchange_create_time DESC
CREATE INDEX IF NOT EXISTS idx_exchangeorder_status_create_time
  ON exchange_orders (status, exchange_create_time DESC)
  WHERE status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED');

-- ExchangeOrder composite index for symbol and status filtering
CREATE INDEX IF NOT EXISTS idx_exchangeorder_symbol_status
  ON exchange_orders (symbol, status)
  WHERE status IN ('NEW', 'ACTIVE', 'PARTIALLY_FILLED');

-- Additional indexes for common query patterns
-- TradeSignal by symbol for signal lookups
CREATE INDEX IF NOT EXISTS idx_tradesignal_symbol_last_update
  ON trade_signals (symbol, last_update_at DESC);

-- ExchangeOrder by symbol for order lookups
CREATE INDEX IF NOT EXISTS idx_exchangeorder_symbol_create_time
  ON exchange_orders (symbol, exchange_create_time DESC);

-- Note: These indexes use partial indexes (WHERE clauses) to reduce index size
-- and improve performance for specific query patterns used by the dashboard endpoint.
