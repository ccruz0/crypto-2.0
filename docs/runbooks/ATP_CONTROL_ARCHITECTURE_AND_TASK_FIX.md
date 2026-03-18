# ATP Control Architecture and /task Fix

## 1. Architecture: Which Service Handles ATP Control Bot

**ATP Control bot is handled by exactly one service: `backend-aws`** (Docker Compose profile `aws`).

| Component | Location | Role |
|-----------|----------|------|
| **Telegram polling** | `backend/app/services/scheduler.py` → `process_telegram_commands()` | Trading scheduler calls `process_telegram_commands` every ~1s |
| **Update fetching** | `backend/app/services/telegram_commands.py` → `get_telegram_updates()` | Long polling via `getUpdates` with `TELEGRAM_BOT_TOKEN` |
| **Command handling** | `backend/app/services/telegram_commands.py` → `handle_telegram_update()` | Single handler for all text commands and callbacks |
| **Container** | `backend-aws` (docker-compose.yml) | Runs gunicorn + uvicorn; scheduler starts in main.py |

**No other service processes ATP Control commands:**
- `market-updater-aws` runs `run_updater.py` (market data) — no scheduler, no Telegram polling
- `backend-aws-canary` has `RUN_TELEGRAM_POLLER=false` — does not poll
- OpenClaw / Claw bot is a different bot (different token) for OpenClaw-native commands

## 2. Command Flow

```
Telegram (user sends /task)
    → getUpdates (polling, TELEGRAM_BOT_TOKEN = ATP_control_bot)
    → process_telegram_commands() [scheduler.py]
    → handle_telegram_update() [telegram_commands.py]
    → Router: text_lower.startswith("/task") or cmd_lower == "/task" → handler_name = "task"
    → Handler: create_task_from_telegram_intent() or show usage
    → send_command_response()
```

**Where /status, /portfolio, /help are implemented:** Same file `telegram_commands.py`, same `handle_telegram_update()`. They are in the same `elif` chain as `/task`.

## 3. Why Deployment Didn't Affect ATP Control

If you deployed `backend-aws` and `/task` still returns "Unknown command", one of these is true:

### A) Another process is polling with the same token

Only one process can poll `getUpdates` for a given bot token. If another process (e.g. local backend on Mac, another EC2, or a script) is polling with the ATP Control token, it receives all updates. The deployed `backend-aws` either:
- Gets no updates (the other process consumes them), or
- Gets 409 Conflict when it tries to poll

**Fix:** Stop any other process that might be polling:
- Local backend: `docker compose --profile local down` or stop uvicorn
- Mac Mini / other host: Stop the backend or any script using `TELEGRAM_BOT_TOKEN`
- Verify: Only `backend-aws` on EC2 should be polling

### B) Docker build used cached layers

`docker compose --profile aws build backend-aws` may use cached layers. If `COPY backend/` was cached from before the `/task` changes, the image has old code.

**Fix:** Force a clean rebuild:
```bash
docker compose --profile aws build --no-cache backend-aws
docker compose --profile aws up -d backend-aws
```

### C) EC2 repo is stale

`deploy_production_via_ssm.sh` runs `git pull origin main`. If your `/task` changes were not pushed to `main`, the EC2 repo does not have them.

**Fix:** Push changes to `main`, then redeploy.

### D) Wrong token (different bot)

ATP Control uses `@ATP_control_bot`. If `TELEGRAM_BOT_TOKEN` points to a different bot (e.g. AWS_alerts_hilovivo_bot), commands in ATP Control never reach the backend. See [TELEGRAM_ATP_CONTROL_TOKEN_FIX.md](TELEGRAM_ATP_CONTROL_TOKEN_FIX.md).

## 4. Verification: Is backend-aws the Active Poller?

On EC2:
```bash
# 1. Confirm backend-aws is running
docker compose --profile aws ps backend-aws

# 2. Confirm /task is in the running code
docker compose --profile aws exec -T backend-aws grep -n "handler_name == \"task\"" /app/app/services/telegram_commands.py || echo "NOT FOUND"

# 3. Check logs for polling
docker compose --profile aws logs backend-aws --tail=100 | grep -E "process_telegram_commands|get_telegram_updates|TG\]"

# 4. If you see "Another poller is active" → another process has the lock
# 5. If you see "409" or "getUpdates conflict" → another process is polling
```

## 5. Fix: Ensure /task Works

The codebase already has:
- `/task` in router (text_lower, cmd_lower)
- `/task` in handler chain (with args, without args, router fallback)
- `/task` in `send_help_message()` (line ~1347)
- `/task` in `setup_bot_commands()` (setMyCommands)
- `cmd:task` in callback handler (menu button)

**If `/task` still fails after deployment:**

1. **Stop competing pollers** — Ensure no other process uses the ATP Control token.
2. **Force rebuild** — `docker compose --profile aws build --no-cache backend-aws && docker compose --profile aws up -d backend-aws`
3. **Confirm token** — Run the verification from [TELEGRAM_ATP_CONTROL_TOKEN_FIX.md](TELEGRAM_ATP_CONTROL_TOKEN_FIX.md); bot username should be `ATP_control_bot`.
4. **Test** — Send `/task` and `/task test description` in ATP Control. Check logs for `telegram_update_received`, `[TG][ROUTER] selected_handler=task`, and absence of `telegram_unknown_command`.

## 6. Files Reference

| File | Purpose |
|------|---------|
| `backend/app/services/telegram_commands.py` | All command handling: /task, /help, /status, /portfolio, callbacks |
| `backend/app/services/scheduler.py` | Calls `process_telegram_commands` in the main loop |
| `backend/app/main.py` | Starts trading scheduler (which runs Telegram polling) |
| `docker-compose.yml` | `backend-aws` service; `backend-aws-canary` has `RUN_TELEGRAM_POLLER=false` |
