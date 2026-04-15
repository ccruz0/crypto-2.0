-- Persist Jarvis Telegram marketing intake metadata (no secret values) across worker restarts.
-- App also ensures this table via ensure_jarvis_marketing_intake_table() at boot.

CREATE TABLE IF NOT EXISTS jarvis_marketing_intake_state (
    chat_id VARCHAR(128) NOT NULL,
    user_id VARCHAR(128) NOT NULL,
    payload TEXT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (chat_id, user_id)
);
