# Telegram `/task` intake (production)

## Correct entrypoint

| Role | Bot (typical) | Where to run `/task` |
|------|----------------|----------------------|
| **ATP production tasks** (Notion, scheduler) | Token: `TELEGRAM_BOT_TOKEN` (or `TELEGRAM_ATP_CONTROL_BOT_TOKEN` if that is the polling token) | **ATP Control Alerts** group / channel configured in env |
| **ATP Alerts** | Same stack, different chat | **Alerts only** — not for `/task` (by design) |
| **Claw** (`TELEGRAM_CLAW_BOT_TOKEN`) | OpenClaw-native control plane | `/task` may be handled by **OpenClaw** on the gateway host; “localhost:8000” errors come from **OpenClaw** calling a local API, not from `backend-aws` |

**Production backend** (`backend-aws`) long-polls Telegram with `get_telegram_token()` priority:

1. `TELEGRAM_BOT_TOKEN`
2. `TELEGRAM_BOT_TOKEN_DEV` (non-AWS)
3. `TELEGRAM_ATP_CONTROL_BOT_TOKEN`
4. `TELEGRAM_CLAW_BOT_TOKEN`

Only **one** token is active per process. Use **`TELEGRAM_BOT_TOKEN` = ATP Control bot** for canonical `/task` intake.

## Authorization env (comma-separated OK)

- **`TELEGRAM_CHAT_ID`** — Primary control chat(s). **Multiple IDs**: `-100xxx,-100yyy` (comma / space / semicolon).
- **`TELEGRAM_ATP_CONTROL_CHAT_ID`** — ATP Control Alerts supergroup(s). **Multiple IDs** supported the same way.
- **`TELEGRAM_AUTH_USER_ID`** — Operator **user** id and/or extra **chat** ids allowed to run commands.

**Bug fixed (2025):** A single env value like `TELEGRAM_CHAT_ID=-100a,-100b` was treated as one string and **never** matched incoming `chat_id`. Parsing now splits lists.

## “Not authorized”

1. Compare **incoming** `chat_id` / `user_id` in logs (`[TG][AUTH][DENY]`) to SSM / `secrets/runtime.env`.
2. Ensure the **ATP Control Alerts** group id is listed under `TELEGRAM_ATP_CONTROL_CHAT_ID` or `TELEGRAM_CHAT_ID`.
3. For DMs, ensure your **numeric user id** is in `TELEGRAM_AUTH_USER_ID`.

## “localhost:8000” (Claw)

Configure the **OpenClaw gateway** (or Cursor bridge) to use the production API base URL, **or** use **ATP Control** bot + backend poller for `/task` instead of Claw.

## Backend `/task` path (ATP Control → `backend-aws`)

| Flow | What runs |
|------|-----------|
| **`/task &lt;description&gt;`** | **`create_notion_task_from_telegram_direct`** only: parses text → **`notion_tasks.create_notion_task`**. **No OpenClaw, no LLM, no** `compile_task_from_intent` / similarity merge. |
| **`/investigate`**, agent flows that register work | May still use **`create_task_from_telegram_intent`** (full pipeline: compile, optional similar-task merge, Notion). |

## Log lines

- `[TG][CONFIG] command_intake` — masked token, chat ids
- `[TG][AUTH] decision=ALLOW|DENY` — `token_source`, `chat_id`, actor/user ids
- `[TG][TASK][INTAKE]` / `[TG][TASK] intake` — `/task` handler
- `[TG][TASK] notion_create_attempt` | `notion_create_success` | `notion_create_failure` — direct Notion write
- `notion_sync_failed` / `Notion task created` — Notion API (see `notion_tasks.py`)
