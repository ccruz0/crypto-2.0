-- Telegram logic watchdog: anomaly log + fix-request queue
-- Idempotent: safe to re-run.

CREATE TABLE IF NOT EXISTS watchdog_anomalies (
    id                  SERIAL PRIMARY KEY,
    fingerprint         VARCHAR(64)  NOT NULL UNIQUE,
    kind                VARCHAR(64)  NOT NULL,
    severity            VARCHAR(16)  NOT NULL DEFAULT 'medium',
    symbol              VARCHAR(50),
    title               VARCHAR(200) NOT NULL,
    detail              TEXT,
    evidence_json       TEXT,
    suspect_paths       TEXT,
    status              VARCHAR(20)  NOT NULL DEFAULT 'new',
    occurrences         INTEGER      NOT NULL DEFAULT 1,
    first_seen_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    last_seen_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    alerted_at          TIMESTAMPTZ,
    resolved_at         TIMESTAMPTZ,
    telegram_message_id INTEGER,
    telegram_chat_id    VARCHAR(50)
);

CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_kind             ON watchdog_anomalies (kind);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_symbol           ON watchdog_anomalies (symbol);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_status           ON watchdog_anomalies (status);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_severity         ON watchdog_anomalies (severity);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_last_seen_at     ON watchdog_anomalies (last_seen_at);
CREATE INDEX IF NOT EXISTS ix_watchdog_anomalies_status_severity  ON watchdog_anomalies (status, severity);

CREATE TABLE IF NOT EXISTS watchdog_fix_requests (
    id             SERIAL PRIMARY KEY,
    anomaly_id     INTEGER     NOT NULL REFERENCES watchdog_anomalies (id) ON DELETE CASCADE,
    status         VARCHAR(20) NOT NULL DEFAULT 'pending',
    requested_by   VARCHAR(50),
    requested_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at     TIMESTAMPTZ,
    finished_at    TIMESTAMPTZ,
    branch         VARCHAR(200),
    commit_sha     VARCHAR(64),
    result_summary TEXT,
    error          TEXT
);

CREATE INDEX IF NOT EXISTS ix_watchdog_fix_requests_anomaly_id   ON watchdog_fix_requests (anomaly_id);
CREATE INDEX IF NOT EXISTS ix_watchdog_fix_requests_status       ON watchdog_fix_requests (status);
CREATE INDEX IF NOT EXISTS ix_watchdog_fix_requests_requested_at ON watchdog_fix_requests (requested_at);
