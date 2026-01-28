-- Create watchlist_signal_states table
-- Idempotent migration

CREATE TABLE IF NOT EXISTS watchlist_signal_states (
    id SERIAL PRIMARY KEY,
    symbol VARCHAR(50) NOT NULL UNIQUE,

    strategy_key VARCHAR(100),
    signal_side VARCHAR(10) DEFAULT 'NONE',

    last_price DOUBLE PRECISION,
    evaluated_at_utc TIMESTAMPTZ,

    alert_status VARCHAR(20) DEFAULT 'NONE',
    alert_block_reason VARCHAR(500),
    last_alert_at_utc TIMESTAMPTZ,

    trade_status VARCHAR(20) DEFAULT 'NONE',
    trade_block_reason VARCHAR(500),
    last_trade_at_utc TIMESTAMPTZ,

    correlation_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS ix_watchlist_signal_states_symbol
    ON watchlist_signal_states(symbol);
