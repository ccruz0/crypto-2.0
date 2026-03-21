# Fix: /investigate and /agent Not Responding in ATP Alerts

**Date:** 2026-03-15

---

## Root Cause Analysis

### Why Commands Were Ignored

1. **PENDING_VALUE_INPUTS consumed commands** (most likely)
   - When the bot was waiting for a value (e.g. amount, symbol) after a watchlist action, *any* message was treated as that value.
   - `/investigate repeated BTC alerts` was parsed as a value input. For `value_type="float"` it failed and sent "⚠️ Valor inválido...". For `value_type="symbol"` it could be accepted as a malformed symbol.
   - **Fix:** Commands (text starting with `/`) now bypass `_handle_pending_value_message` and go straight to the command router.

2. **Token mismatch on local runtime** (if testing locally)
   - Polling used `BOT_TOKEN_DEV` but `send_command_response` always used `BOT_TOKEN`.
   - Responses could be sent with the wrong bot token, so the user might not see them.
   - **Fix:** `send_command_response` now uses `_get_effective_bot_token()` (DEV on local, PROD on AWS).

3. **Lack of debug visibility**
   - No explicit log when routing to `/investigate` or `/agent`.
   - **Fix:** Added `[TG][CMD] Routing /investigate to agent handler` and similar logs.

---

## Patch Summary

### Files Modified

| File | Change |
|------|--------|
| `backend/app/services/telegram_commands.py` | See below |

### Changes

1. **`_handle_pending_value_message`** — Do not consume commands:
   ```python
   # Never consume commands — let them reach the command router
   if text.strip().startswith("/"):
       return False
   ```

2. **`_get_effective_bot_token()`** — New helper to match polling token:
   - Local + `BOT_TOKEN_DEV` → use DEV token for sending
   - AWS → use `BOT_TOKEN`

3. **`send_command_response`** — Use effective token instead of always `BOT_TOKEN`.

4. **Debug logging** — Log routing for `/investigate` and `/agent`:
   - `[TG][CMD] Routing /investigate to agent handler chat_id=%s text=%s`
   - `[TG][CMD] Routing /agent to agent handler chat_id=%s text=%s`

5. **Agent Console menu** — Added "🔍 Investigate" and "🔧 Runtime Check" buttons.

6. **Callback handlers** — Added `cmd:investigate` and `cmd:runtime-check`:
   - `cmd:investigate` → Sends usage prompt
   - `cmd:runtime-check` → Runs runtime check and sends result

---

## Verification

### Expected Behavior

When the user sends:
```
/investigate repeated BTC alerts
```

The backend should:
1. **Acknowledge** — "Task received\nAgent selected: Sentinel\nReason: ...\nMode: analysis"
2. **Select agent** — Sentinel (for alert-related issues)
3. **Execute** — OpenClaw analysis
4. **Reply** — "Run complete\nAgent: Sentinel\nValidation: PASSED/FAILED\n..."

### How to Confirm

1. **Check logs** for:
   - `[TG][CMD] Routing /investigate to agent handler chat_id=... text=/investigate repeated BTC alerts`
   - `telegram_command_received command=investigate chat_id=...`

2. **Send** `/investigate repeated BTC alerts` in ATP Alerts.

3. **Verify** you receive at least the acknowledgment within ~30 seconds (poll interval + processing).

### If Still No Response

- Ensure `TELEGRAM_CHAT_ID` (or `TELEGRAM_AUTH_USER_ID`) includes the ATP Alerts channel/group ID.
- Check backend logs for `[TG][DENY]` (authorization failure).
- Check for `[TG][ERROR] Failed to send command response` (send failure).
- Verify OpenClaw is configured (`OPENCLAW_API_URL`, `OPENCLAW_API_TOKEN`).
