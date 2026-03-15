# ATP Control Telegram Command Fix

**Date:** 2026-03-15  
**Issue:** /start and test message work; /help, /runtime-check, /investigate, /agent produce no visible reply.

## Root Cause (Hypothesis)

The exact root cause was not definitively identified from code inspection. Possible contributors:

1. **Message length / HTML parse errors** — Telegram 4096-char limit or malformed HTML causing send failure
2. **Silent early returns** — Non-command path returned without sending any reply
3. **Token consistency** — `answerCallbackQuery` used `BOT_TOKEN` directly instead of `_get_effective_bot_token()`

## Fix Summary

### 1. `send_command_response` (telegram_commands.py)

- **Truncation:** Messages > 4096 chars are truncated with a note
- **Fallbacks:** On HTTP error or HTML parse failure, retry without `parse_mode`; on exception, retry plain text
- **Logging:** More detailed error logging (status, chat_id, error payload)

### 2. Non-command path

- **Before:** `return` without sending (silent drop)
- **After:** `send_command_response(chat_id, "❓ Send a command (e.g. /help)")` then return

### 3. `answerCallbackQuery` token

- **Before:** Used `BOT_TOKEN` directly
- **After:** Uses `_get_effective_bot_token()` for consistency with local/AWS runtime

### 4. Diagnostics

- Added `[TG][REPLY]` logging for `/investigate` and `/agent` handlers (success/failure)
- Existing `[TG][CHAT]`, `[TG][AUTH]`, `[TG][CMD]` logs remain

## Files Changed

- `backend/app/services/telegram_commands.py`

## Deployment

1. Push to main: `git push origin main`
2. Deploy backend via normal AWS path (e.g. SSM, EICE, or backend deploy script)
3. Restart backend-aws container/service

## Validation

After deploy, test in ATP Control (direct chat or private group):

| Command | Expected |
|---------|----------|
| /start | Main menu with inline buttons |
| /help | Command help message |
| /runtime-check | Runtime dependency check output |
| /investigate repeated BTC alerts | Task ack + agent run result |
| /agent sentinel investigate repeated BTC alerts | Task ack + agent run result |

Capture logs for each: `[TG][CHAT]`, `[TG][AUTH]`, `[TG][CMD]`, `[TG][REPLY]`.
