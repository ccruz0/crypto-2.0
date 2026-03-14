# Real addresses (from documentation)

Reference list of URLs, IDs, and config locations used in this project. No secret values are stored here.

## Dashboard and API

| What | Address / value |
|------|------------------|
| **Dashboard (PROD)** | `https://dashboard.hilovivo.com` |
| **API base** | `https://dashboard.hilovivo.com/api` |
| **Health** | `https://dashboard.hilovivo.com/api/health` |
| **System health** | `https://dashboard.hilovivo.com/api/health/system` |
| **OpenClaw UI** | `https://dashboard.hilovivo.com/openclaw/` |
| **OpenClaw WebSocket** | `wss://dashboard.hilovivo.com/openclaw/ws` |

Source: `scripts/aws/prod_status.sh`, `docs/runbooks/dashboard_healthcheck.md`, `docs/openclaw/OPENCLAW_END_TO_END_EXECUTION.md`, `docs/debug/dashboard-dns-update-instructions.md`.

## Notion

| What | Address / value |
|------|------------------|
| **AI Task System database ID** | `eb90cfa139f94724a8b476315908510a` |
| **Database URL (example)** | `https://www.notion.so/eb90cfa139f94724a8b476315908510a?v=...` (open in browser; the 32-char hex is the database ID). |

Where the **Notion secret** (API key) and this ID are stored: [secrets_runtime_env.md § Where the Notion secret and database ID are stored](secrets_runtime_env.md#where-the-notion-secret-and-database-id-are-stored) — locally `backend/.env`, on server `secrets/runtime.env`.

## Telegram

| What | Address / value |
|------|------------------|
| **Chat ID in .env.prod.example** | `839853931` (used as production channel in examples). |
| **Docs note** | [docs/monitoring/telegram_channel_id_fix.md](../monitoring/telegram_channel_id_fix.md) states that `839853931` is a **private chat** (user), not the channel. For the **channel** "Hilovivo-alerts" / "ilovivoalerts", the real chat ID is a **negative** number (e.g. `-1001234567890`). |
| **How to get real channel ID** | Add the bot as admin to the channel, send a message in the channel, then: `curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getUpdates"` and look for `"chat":{"id":-100...}`; or forward a channel message to @userinfobot to see the channel’s chat_id. |
| **Where Telegram is set** | Server: `secrets/runtime.env` (and optionally `.env.aws`). Local: `backend/.env` for `TELEGRAM_CHAT_ID`; bot token from `TELEGRAM_BOT_TOKEN_ENCRYPTED` in `secrets/runtime.env` when `secrets/telegram_key` exists, or plaintext `TELEGRAM_BOT_TOKEN` in `backend/.env`. |

So: the **real address** for the Telegram **channel** is the negative `chat_id` you obtain for "Hilovivo-alerts"; the repo only documents the procedure, not the actual channel ID.

## AWS

| What | Address / value |
|------|------------------|
| **PROD instance ID** | `i-087953603011543c5` (atp-rebuild-2026) |
| **LAB instance ID** | `i-0d82c172235770a0d` (atp-lab-ssm-clean) |
| **Region** | `ap-southeast-1` (used in prod_status.sh and SSM scripts) |

Source: `scripts/aws/prod_status.sh`, `scripts/run_notion_task_pickup_via_ssm.sh`.

## File paths (secrets / config)

| What | Path |
|------|------|
| **Notion + Telegram (local)** | `backend/.env` |
| **Runtime secrets (server)** | `secrets/runtime.env` |
| **Telegram decrypt key** | `secrets/telegram_key` (must exist for `TELEGRAM_BOT_TOKEN_ENCRYPTED` to decrypt locally). |

See [secrets_runtime_env.md](secrets_runtime_env.md) for what lives in `runtime.env` and where the Notion secret is stored.
