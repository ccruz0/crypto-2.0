# Telegram Command Routing Fix — /help and /runtime-check

**Date:** 2026-03-15

---

## 1. Root Cause

**Investigation summary:** /start works because it uses `show_main_menu` → `_send_menu_message`, which sent with `BOT_TOKEN` directly. `/help` and `/runtime-check` use `send_command_response` → `_get_effective_bot_token()`. On AWS both use the same token, so token mismatch was ruled out.

**Identified issues:**

1. **Deduplication silent drop** — When the same command was processed within 3 seconds (e.g. duplicate delivery or race), the code returned early **without sending any reply**. User saw no response.

2. **Inconsistent token usage** — `_send_menu_message`, `_edit_menu_message`, and callback `answerCallbackQuery` used `BOT_TOKEN` directly. `send_command_response` used `_get_effective_bot_token()`. On local with `BOT_TOKEN_DEV`, menu could go to the wrong bot.

3. **Missing reply on edge cases** — Empty text, non-command text, and fallback paths did not always send an acknowledgment.

4. **Insufficient logging** — `[TG][REPLY]` was at DEBUG level; hard to confirm delivery in production logs.

---

## 2. Files Changed

| File | Change |
|------|--------|
| `backend/app/services/telegram_commands.py` | Use `_get_effective_bot_token()` in `_send_menu_message`, `_edit_menu_message`, remove_keyboard, deleteMessage; add empty-text and non-command guards; send reply on dedup skip; add `[TG][REPLY]` logging for help/runtime-check/unknown; add fallback else clause; raise `[TG][REPLY]` to INFO |

---

## 3. Fix Summary

- **Deduplication:** When skipping a duplicate command, now sends "⏳ Command already processed. Wait a moment and try again." instead of returning silently.
- **Token:** All send paths use `_get_effective_bot_token()` for consistency (local dev vs AWS).
- **Guards:** Empty text → "📋 Send a command (e.g. /help)". Non-command text → return (no reply for non-commands).
- **Fallback:** Final `else` sends "❓ No response. Use /help for commands." for any unmatched path.
- **Logging:** `[TG][REPLY]` at INFO with handler name and success for help, runtime-check, unknown.

---

## 4. Deployment

- Push to `main` triggers `Deploy to AWS EC2 (Session Manager)`.
- Verify: `docker compose --profile aws logs -n 100 backend-aws` for `[TG][CMD]` and `[TG][REPLY]`.

---

## 5. Validation Commands

| Command | Expected |
|---------|----------|
| `/start` | Main menu with buttons |
| `/help` | Full command list |
| `/runtime-check` | Runtime dependency status |
| `/investigate repeated BTC alerts` | Task received, agent selected |
| `/agent sentinel investigate repeated BTC alerts` | Task received, Sentinel |

**Log checks:** `[TG][INTAKE]`, `[TG][AUTH] decision=ALLOW`, `[TG][CMD] handler=help`, `[TG][REPLY] success=True`.
