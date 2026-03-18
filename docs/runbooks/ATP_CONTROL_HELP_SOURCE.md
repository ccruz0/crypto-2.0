# ATP Control /help Source — Exact Path

## Root cause

**ATP Control /help and all commands are served by exactly one path:**

| Item | Value |
|------|-------|
| **File** | `backend/app/services/telegram_commands.py` |
| **Function** | `send_help_message(chat_id)` (for /help content) |
| **Handler** | `handle_telegram_update(update, db)` (for all commands) |
| **Service** | `backend-aws` (Docker Compose profile `aws`) |
| **Token** | `TELEGRAM_BOT_TOKEN` / `TELEGRAM_BOT_TOKEN_AWS` (ATP_control_bot) |

There is no other handler. `/status`, `/portfolio`, `/signals`, `/help`, `/task` all go through `handle_telegram_update` → the same `elif` chain.

## Why /help might not show /task

1. **Stale deployment** — The running container has an older `telegram_commands.py` without `/task` in `send_help_message`.
2. **Another process polling** — A different process (e.g. local backend) polls with the same token and has old code. It receives updates first; backend-aws never sees them.
3. **Changes not pushed** — `git pull origin main` on EC2 only gets updates that are on `origin/main`. If changes were not committed and pushed, the deploy uses old code.

## Exact flow

```
User sends /help in ATP Control
    → Telegram API delivers update to whoever polls getUpdates
    → process_telegram_commands() [scheduler.py]
    → handle_telegram_update(update, db) [telegram_commands.py]
    → elif text.startswith("/help"): send_help_message(chat_id)
    → send_help_message builds message and calls send_command_response()
```

## Verification

**1. Confirm `/task` in the running code:**
```bash
# On EC2 (or via SSM)
docker compose --profile aws exec -T backend-aws grep -n "/task" /app/app/services/telegram_commands.py | head -20
```
You should see `/task` in `send_help_message` and in the `elif` handler chain.

**2. Confirm no other poller:**
```bash
docker compose --profile aws logs backend-aws --tail=200 | grep -E "409|Another poller|getUpdates conflict"
```
If you see 409 or "Another poller", another process is polling.

**3. Test /help:**
Send `/help` in ATP Control. You should see `/task` in the list (right after `/help`). If you do not, the running code is old (see above).

## Files changed (this fix)

- `backend/app/services/telegram_commands.py`
  - `send_help_message()`: moved `/task` to appear right after `/help` in the help text
  - `/task` was already in the handler chain; no change needed there

## Deploy

```bash
# 1. Commit and push
git add backend/app/services/telegram_commands.py
git commit -m "fix: ensure /task in ATP Control help (telegram_commands.py)"
git push origin main

# 2. Deploy with no-cache
NO_CACHE=1 ./scripts/deploy_production_via_ssm.sh
```

## Production check

After deploy:
1. Send `/help` in ATP Control → `/task` should appear in the list.
2. Send `/task` → usage or task created.
3. Send `/task test description` → task created or reused.
