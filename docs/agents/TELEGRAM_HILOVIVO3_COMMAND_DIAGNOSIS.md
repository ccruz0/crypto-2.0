# Telegram ATP Alerts Command Diagnosis — Root Cause and Fix

**Date:** 2026-03-15

---

## 1. Root-Cause Summary

Commands in ATP Alerts (formerly HILOVIVO3.0) were ignored because of **ignored update type** and **auth mismatch**:

1. **Channel posts not requested** — `allowed_updates` did not include `channel_post` or `edited_channel_post`. In Telegram channels, user/admin posts arrive as `channel_post`, not `message`. The bot never received these updates.

2. **Channel posts not handled** — `handle_telegram_update` only read `message` and `edited_message`. It never checked `channel_post` or `edited_channel_post`.

3. **Auth mismatch** — Command authorization used `TELEGRAM_CHAT_ID` and `TELEGRAM_AUTH_USER_ID`. Alerts use `TELEGRAM_CHAT_ID_TRADING` (ATP Alerts). If ATP Alerts was configured only as `TELEGRAM_CHAT_ID_TRADING` and not in the command auth list, commands would be denied even if received.

---

## 2. Files Involved

| File | Role |
|------|------|
| `backend/app/services/telegram_commands.py` | Polling, update handling, command routing, auth |
| `backend/app/services/telegram_notifier.py` | Outbound alerts (TELEGRAM_CHAT_ID_TRADING for ATP Alerts) |
| `backend/app/core/config.py` | Env var definitions |
| `backend/app/main.py` | Startup: copies TELEGRAM_BOT_TOKEN_AWS → TELEGRAM_BOT_TOKEN |

---

## 3. Problem Classification

| Category | Status |
|----------|--------|
| **Different bot** | No — same bot token for outbound and inbound |
| **Wrong chat type** | Yes — channel posts use `channel_post`, not `message` |
| **Missing permissions** | No — bot can send to channel (alerts work) |
| **Auth mismatch** | Yes — TELEGRAM_CHAT_ID_TRADING was not in command auth |
| **Ignored update type** | Yes — `channel_post` not in `allowed_updates`, not handled |

---

## 4. Minimal Fix Applied

### 4.1 Request and handle channel posts

```python
# get_telegram_updates: add to allowed_updates
params["allowed_updates"] = [
    "message", "edited_message",
    "channel_post", "edited_channel_post",
    "my_chat_member", "callback_query",
]

# handle_telegram_update: extract message from channel_post
message = (
    update.get("message")
    or update.get("edited_message")
    or update.get("channel_post")
    or update.get("edited_channel_post")
)
```

### 4.2 Authorize TELEGRAM_CHAT_ID_TRADING

```python
# At startup: add ATP Alerts to authorized list
if _env_chat_id_trading and str(_env_chat_id_trading) not in AUTHORIZED_USER_IDS:
    AUTHORIZED_USER_IDS.add(str(_env_chat_id_trading))
```

### 4.3 Diagnostic logging

- `[TG][INTAKE]` — update_source, chat_id, chat_type, user_id, text
- `[TG][DENY]` — full auth context when blocked
- `[TG][AUTH]` — when authorized
- `[TG] ⚡ Processing` — channel_post vs message, chat_type

---

## 5. Bot Token Usage (Same Bot)

| Path | Token source | Chat ID source |
|------|--------------|----------------|
| **Outbound alerts** | `TELEGRAM_BOT_TOKEN_AWS` or `TELEGRAM_BOT_TOKEN` | `TELEGRAM_CHAT_ID_TRADING` (ATP Alerts) |
| **Inbound commands** | `TELEGRAM_BOT_TOKEN` (main.py copies from _AWS if needed) | Auth: `TELEGRAM_CHAT_ID`, `TELEGRAM_AUTH_USER_ID`, `TELEGRAM_CHAT_ID_TRADING` |

Same bot is used for both. No token mismatch.

---

## 6. Chat Type Handling

| Chat type | Update field | Now supported |
|-----------|--------------|---------------|
| private | `message` | Yes |
| group | `message` | Yes |
| supergroup | `message` | Yes |
| channel | `channel_post` | Yes (after fix) |

Channel IDs are typically `-100xxxxxxxxxx`. Auth supports them via `AUTHORIZED_USER_IDS` and `AUTH_CHAT_ID`.

---

## 7. Operator Setup Recommendations

### Option A: ATP Alerts (channel) — now supported

1. Set `TELEGRAM_CHAT_ID_TRADING` to ATP Alerts channel ID (e.g. `-1003820753438`).
2. Ensure the bot is an admin in the channel (required to receive `channel_post`).
3. Deploy the fix so `channel_post` is requested and handled.

### Option B: Direct chat with ATP bot

1. Start a private chat with the ATP bot.
2. Add your user ID to `TELEGRAM_AUTH_USER_ID`.
3. Commands use `message`; no channel_post handling needed.

### Option C: Private supergroup

1. Create a private supergroup and add the bot.
2. Add the group’s chat ID to `TELEGRAM_AUTH_USER_ID` or `TELEGRAM_CHAT_ID`.
3. Commands use `message`; works like a group.

---

## 8. Verification

After deploying:

1. Send `/investigate repeated BTC alerts` in ATP Alerts.
2. Check logs for:
   - `[TG][INTAKE] update_source=channel_post chat_id=-100... chat_type=channel`
   - `[TG][AUTH] ✅ Authorized`
   - `[TG][CMD] Routing /investigate`
3. Confirm you receive a reply in the channel.
