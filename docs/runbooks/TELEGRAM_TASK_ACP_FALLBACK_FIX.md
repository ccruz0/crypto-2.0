# /task Fallback Fix: ATP Control Token Resolution

## Problem

When `/task` returns a generic fallback message (e.g. "Unknown command", no response, or "ACP runtime backend not configured" from an external service), the root cause is often that the **Telegram poller uses the wrong or missing bot token**.

The backend polls `getUpdates` with the token from `get_telegram_token()`. If that returns `None` or a token for a different bot, commands sent to ATP Control (@ATP_control_bot) are never received.

## Root Cause

- **telegram_token_loader** previously only read `TELEGRAM_BOT_TOKEN` and `TELEGRAM_BOT_TOKEN_DEV`
- Deploys that set only `TELEGRAM_ATP_CONTROL_BOT_TOKEN` (e.g. SSM atp_control_bot_token) had no token for polling
- `TELEGRAM_ENABLED` was `False` → `get_telegram_updates()` returned `[]` → no commands processed

## Fix Applied

1. **telegram_token_loader.py**: Added fallback chain:
   - `TELEGRAM_BOT_TOKEN` → `TELEGRAM_BOT_TOKEN_DEV` → `TELEGRAM_ATP_CONTROL_BOT_TOKEN` → `TELEGRAM_CLAW_BOT_TOKEN` → interactive prompt

2. **render_runtime_env.sh**: When `TELEGRAM_BOT_TOKEN` or `TELEGRAM_CHAT_ID` is empty, use `TELEGRAM_ATP_CONTROL_*` values so the poller can run with ATP Control config only.

3. **Regression test**: `test_task_token_fallback_atp_control` ensures the fallback works.

## Verification

### 1. Check token resolution

```bash
cd /path/to/automated-trading-platform
# With ATP Control vars only (no TELEGRAM_BOT_TOKEN)
TELEGRAM_ATP_CONTROL_BOT_TOKEN=test TELEGRAM_ATP_CONTROL_CHAT_ID=123 \
  python -c "
from app.utils.telegram_token_loader import get_telegram_token
t = get_telegram_token()
print('Token resolved:', 'YES' if t else 'NO')
"
# Expected: Token resolved: YES
```

### 2. Run regression test

```bash
.venv/bin/python -m pytest backend/tests/test_telegram_task_command.py::test_task_token_fallback_atp_control -v
```

### 3. Live /task test

1. Ensure `TELEGRAM_ATP_CONTROL_BOT_TOKEN` and `TELEGRAM_ATP_CONTROL_CHAT_ID` are set in runtime.env (or TELEGRAM_BOT_TOKEN = ATP Control token)
2. Restart backend: `docker compose --profile aws up -d --force-recreate backend-aws`
3. Send `/task test task` in ATP Control Telegram channel
4. Expected: "✅ Task created" or "✅ Matched existing task" (not "Unknown command" or generic fallback)

### 4. Log patterns

When /task works, logs show:
- `[TG][ROUTER] selected_handler=task`
- `telegram_task_command_received chat_id=... intent_len=...`
- `telegram_task_command_processed chat_id=... ok=True`

When token fallback is used:
- `[TG] Using TELEGRAM_ATP_CONTROL_BOT_TOKEN for polling (TELEGRAM_BOT_TOKEN not set)`

## Files Changed

| File | Change |
|------|--------|
| `backend/app/utils/telegram_token_loader.py` | Fallback to TELEGRAM_ATP_CONTROL_BOT_TOKEN, TELEGRAM_CLAW_BOT_TOKEN |
| `scripts/aws/render_runtime_env.sh` | Use ATP Control token/chat when primary not set |
| `backend/tests/test_telegram_task_command.py` | test_task_token_fallback_atp_control |
