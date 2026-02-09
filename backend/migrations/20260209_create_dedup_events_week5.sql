-- Week 5: dedup_events table for actionable event deduplication (TTL window).
-- Idempotent: safe to run multiple times (IF NOT EXISTS).
-- Run: PGPASSWORD=... psql -U trader -d atp -f backend/migrations/20260209_create_dedup_events_week5.sql

CREATE TABLE IF NOT EXISTS dedup_events (
    id SERIAL PRIMARY KEY,
    created_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() AT TIME ZONE 'UTC'),
    key TEXT NOT NULL,
    correlation_id TEXT,
    symbol TEXT,
    action TEXT,
    payload_json TEXT,
    UNIQUE(key)
);

CREATE INDEX IF NOT EXISTS idx_dedup_events_created_at ON dedup_events (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_dedup_events_key ON dedup_events (key);

COMMENT ON TABLE dedup_events IS 'Week 5: Dedup keys for actionable events (order/alert) within TTL window; key=hash(symbol,side,strategy,timeframe,trigger_price_bucket,time_bucket)';
