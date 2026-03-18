# Investigation-Complete Telegram Dedup: DB-Backed

## Previous Issue

Investigation-complete messages (ROOT CAUSE, PROPOSED CHANGE, TASK AI Task Execution Template) were sent repeatedly in ATP Control, appearing in a loop. Dedup relied on:

- **In-memory cache** (`_INVESTIGATION_INFO_SENT`) — lost on restart
- **`logs/agent_activity.jsonl`** — ephemeral in Docker; not persisted across restarts

After a container restart or when the same Notion task was re-executed, the same Telegram info message could be sent again.

## Solution: DB-Backed Dedup

Dedup now uses **TradingSettings** (PostgreSQL) as the source of truth:

- **Key format:** `agent_info_dedup:investigation_complete:<task_id>`
- **Value:** ISO timestamp of last send
- **Cooldown:** 24 hours (`_INVESTIGATION_INFO_DEDUP_HOURS`)

Behavior:

- Before sending: check DB for last-sent timestamp
- If within cooldown: skip send
- If outside cooldown or not found: send and update DB

## JSONL Is No Longer Source of Truth

`logs/agent_activity.jsonl` is still used for **operational logging** (`investigation_info_sent` events) but is **not** used for dedup. Dedup is exclusively DB-backed.

## Files Changed

- `backend/app/services/agent_telegram_approval.py` — DB helpers, `_should_skip_investigation_info_dedup` now uses TradingSettings
- `backend/tests/test_investigation_info_dedup.py` — tests for dedup behavior
- `docs/agents/INVESTIGATION_INFO_DEDUP_DB.md` — this doc

## Manual Verification

1. Trigger an investigation-complete flow (e.g. OpenClaw task completion).
2. Confirm one Telegram message is sent.
3. Re-trigger the same task (or restart backend and re-run).
4. Confirm no duplicate message within 24h.
5. Optionally, check DB: `SELECT * FROM trading_settings WHERE setting_key LIKE 'agent_info_dedup:investigation_complete:%';`
