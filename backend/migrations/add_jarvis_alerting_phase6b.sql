-- Phase 6B: Autonomous alerting and daily health reports (read-only)

CREATE TABLE IF NOT EXISTS jarvis_alerts (
    id SERIAL PRIMARY KEY,
    alert_id TEXT NOT NULL UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    severity TEXT NOT NULL,
    source TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    evidence TEXT NOT NULL DEFAULT '[]',
    investigation_id TEXT,
    occurrence_count INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'open',
    first_seen TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_jarvis_alerts_status ON jarvis_alerts (status, last_seen DESC);
CREATE INDEX IF NOT EXISTS idx_jarvis_alerts_fingerprint ON jarvis_alerts (fingerprint, status);
CREATE INDEX IF NOT EXISTS idx_jarvis_alerts_severity ON jarvis_alerts (severity, last_seen DESC);

CREATE TABLE IF NOT EXISTS jarvis_daily_reports (
    id SERIAL PRIMARY KEY,
    report_id TEXT NOT NULL UNIQUE,
    report_date DATE NOT NULL UNIQUE,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    summary_json TEXT NOT NULL DEFAULT '{}'
);
