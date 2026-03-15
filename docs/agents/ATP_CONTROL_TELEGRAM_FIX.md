# ATP Control Telegram Command Fix

**Date:** 2026-03-15  
**Issue:** /start and test message work; /help, /runtime-check, /investigate, /agent produce no visible reply.

## Root Cause (Confirmed)

**Telegram sends commands with @botname in groups:** `/help@ATP_control_bot`, `/investigate@ATP_control_bot repeated BTC alerts`.

The previous normalization used `text.split("@")[0]`, which:
- For `/help@ATP_control_bot` → `/help` ✓
- For `/investigate@ATP_control_bot repeated BTC alerts` → `/investigate` ✗ (arguments lost)

Handlers like `handle_investigate_command` expect the full text with args. Without args, parsing fails or routes incorrectly.

### Emergency fix (2026-03-15): /start stopped working

**Hypothesis:** `message.get("text", "")` can return `None` when key exists with null value; `text.strip()` then throws. Or normalization edge case produced empty string.

**Fix:** 
- `text = (text or "").strip()` to handle None
- Wrap normalization in try/except with fallback to `split("@")[0]`
- If regex produces empty, fallback to old split logic
- Add [TG][TEXT], [TG][ROUTER], [TG][HANDLER], [TG][ERROR] logging

## Previous Hypotheses (superseded)

1. **Message length / HTML parse errors** — Possible but secondary
2. **Silent early returns** — Fixed in prior commit
3. **Token consistency** — Fixed in prior commit

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
