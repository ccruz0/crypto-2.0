-- Migration: Create watchlist_master table (source of truth for Watchlist UI)
-- This table stores all watchlist data with per-field timestamp tracking

CREATE TABLE IF NOT EXISTS watchlist_master (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    exchange TEXT NOT NULL DEFAULT 'CRYPTO_COM',
    is_deleted BOOLEAN NOT NULL DEFAULT 0,
    
    -- User-configurable fields
    buy_target REAL,
    take_profit REAL,
    stop_loss REAL,
    trade_enabled BOOLEAN NOT NULL DEFAULT 0,
    trade_amount_usd REAL,
    trade_on_margin BOOLEAN NOT NULL DEFAULT 0,
    alert_enabled BOOLEAN NOT NULL DEFAULT 0,
    buy_alert_enabled BOOLEAN NOT NULL DEFAULT 0,
    sell_alert_enabled BOOLEAN NOT NULL DEFAULT 0,
    sl_tp_mode TEXT NOT NULL DEFAULT 'conservative',
    min_price_change_pct REAL,
    alert_cooldown_minutes REAL,
    sl_percentage REAL,
    tp_percentage REAL,
    sl_price REAL,
    tp_price REAL,
    notes TEXT,
    signals TEXT, -- JSON string
    skip_sl_tp_reminder BOOLEAN NOT NULL DEFAULT 0,
    
    -- Market data fields (updated by background jobs)
    price REAL,
    rsi REAL,
    atr REAL,
    ma50 REAL,
    ma200 REAL,
    ema10 REAL,
    res_up REAL,
    res_down REAL,
    volume_ratio REAL,
    current_volume REAL,
    avg_volume REAL,
    volume_24h REAL,
    
    -- Order/position fields
    order_status TEXT NOT NULL DEFAULT 'PENDING',
    order_date TEXT, -- ISO format datetime
    purchase_price REAL,
    quantity REAL,
    sold BOOLEAN NOT NULL DEFAULT 0,
    sell_price REAL,
    
    -- Timestamps
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    
    -- Per-field update timestamps (JSONB-like structure stored as TEXT)
    -- Format: {"price": "2024-01-01T12:00:00Z", "rsi": "2024-01-01T12:01:00Z", ...}
    field_updated_at TEXT, -- JSON string mapping field names to ISO timestamps
    
    -- Unique constraint
    UNIQUE(symbol, exchange)
);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_watchlist_master_symbol ON watchlist_master(symbol);
CREATE INDEX IF NOT EXISTS idx_watchlist_master_is_deleted ON watchlist_master(is_deleted);

-- Migrate existing data from watchlist_items to watchlist_master
-- This ensures the master table is never empty
INSERT OR IGNORE INTO watchlist_master (
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
    symbol, exchange, COALESCE(is_deleted, 0),
    buy_target, take_profit, stop_loss,
    COALESCE(trade_enabled, 0), trade_amount_usd, COALESCE(trade_on_margin, 0),
    COALESCE(alert_enabled, 0), 
    COALESCE(buy_alert_enabled, 0), 
    COALESCE(sell_alert_enabled, 0),
    COALESCE(sl_tp_mode, 'conservative'), min_price_change_pct, alert_cooldown_minutes,
    sl_percentage, tp_percentage, sl_price, tp_price,
    notes, signals, COALESCE(skip_sl_tp_reminder, 0),
    price, rsi, atr, ma50, ma200, ema10, res_up, res_down,
    COALESCE(order_status, 'PENDING'), order_date, purchase_price, quantity, 
    COALESCE(sold, 0), sell_price,
    COALESCE(created_at, datetime('now')), 
    COALESCE(updated_at, datetime('now'))
FROM watchlist_items
WHERE is_deleted = 0 OR is_deleted IS NULL;

-- Enrich with MarketData if available
UPDATE watchlist_master
SET 
    price = (SELECT price FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    rsi = (SELECT rsi FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    atr = (SELECT atr FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    ma50 = (SELECT ma50 FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    ma200 = (SELECT ma200 FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    ema10 = (SELECT ema10 FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    res_up = (SELECT res_up FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    res_down = (SELECT res_down FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    volume_ratio = (SELECT volume_ratio FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    current_volume = (SELECT current_volume FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    avg_volume = (SELECT avg_volume FROM market_data WHERE market_data.symbol = watchlist_master.symbol),
    volume_24h = (SELECT volume_24h FROM market_data WHERE market_data.symbol = watchlist_master.symbol)
WHERE EXISTS (SELECT 1 FROM market_data WHERE market_data.symbol = watchlist_master.symbol);

