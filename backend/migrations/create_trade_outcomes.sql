-- Migration: Create trade_outcomes table (Phase 1a — LAB-safe foundation)
-- Date: 2026-08-05
-- Description: Round-trip fact table for own-trade learning labels (entry → SL/TP exit).
-- Does NOT wire Auto ML promote (Phase 1b). Apply on LAB first:
--   psql -U trader -d atp -f backend/migrations/create_trade_outcomes.sql
-- Idempotent.

CREATE TABLE IF NOT EXISTS trade_outcomes (
    id SERIAL PRIMARY KEY,
    telegram_message_id INTEGER,
    order_intent_id INTEGER,
    entry_exchange_order_id VARCHAR(100) NOT NULL,
    exit_exchange_order_id VARCHAR(100),
    symbol VARCHAR(50) NOT NULL,
    side VARCHAR(10) NOT NULL,
    entry_price NUMERIC(20, 8),
    exit_price NUMERIC(20, 8),
    quantity NUMERIC(20, 8),
    pnl_usd NUMERIC(20, 8),
    pnl_pct NUMERIC(20, 8),
    exit_reason VARCHAR(32),
    label INTEGER,
    entry_ts TIMESTAMPTZ,
    exit_ts TIMESTAMPTZ,
    hold_seconds INTEGER,
    join_status VARCHAR(32) NOT NULL DEFAULT 'COMPLETE',
    source VARCHAR(32) NOT NULL DEFAULT 'exchange_orders',
    meta_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    CONSTRAINT uq_trade_outcomes_entry_exchange_order_id UNIQUE (entry_exchange_order_id)
);

CREATE INDEX IF NOT EXISTS ix_trade_outcomes_telegram_message_id
    ON trade_outcomes (telegram_message_id);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_order_intent_id
    ON trade_outcomes (order_intent_id);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_symbol ON trade_outcomes (symbol);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_exit_reason ON trade_outcomes (exit_reason);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_label ON trade_outcomes (label);
CREATE INDEX IF NOT EXISTS ix_trade_outcomes_entry_ts ON trade_outcomes (entry_ts);

COMMENT ON TABLE trade_outcomes IS
    'Phase 1a round-trip labels: telegram→intent→entry→SL/TP fill. Offline builder only.';
COMMENT ON COLUMN trade_outcomes.label IS
    '1 if pnl_usd > 0, 0 if pnl_usd <= 0, NULL if incomplete (should not persist COMPLETE without label)';
COMMENT ON COLUMN trade_outcomes.exit_reason IS
    'TAKE_PROFIT | STOP_LOSS | UNKNOWN (inferred from child order_role / order_type)';
COMMENT ON COLUMN trade_outcomes.join_status IS
    'COMPLETE for persisted rounds; builder also reports drop reasons in coverage JSON';
