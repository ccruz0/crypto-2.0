-- Migration: Add telegram update deduplication table
-- Prevents duplicate processing when multiple pollers or instances receive the same update.
-- Usage: psql -U trader -d atp -f backend/migrations/add_telegram_update_dedup.sql

CREATE TABLE IF NOT EXISTS telegram_update_dedup (
    update_id BIGINT PRIMARY KEY,
    received_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_telegram_update_dedup_received_at
ON telegram_update_dedup(received_at);
