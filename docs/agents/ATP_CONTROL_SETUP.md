# ATP Control Setup Guide

**Version:** 1.0  
**Date:** 2026-03-15

ATP Control is the command/control interface for ATP agent operations. Use a **private group** or **direct bot chat** — not ATP Alerts (alerts-only).

---

## Prerequisites

- Bot token configured (`TELEGRAM_BOT_TOKEN` on AWS, `TELEGRAM_BOT_TOKEN_DEV` for local)
- ATP backend running

---

## Option A: Direct Bot Chat

1. Open Telegram and search for your ATP bot.
2. Start a chat with the bot.
3. Get your user ID:
   - Use [@userinfobot](https://t.me/userinfobot) or similar
   - Or check logs when you send a message: `[TG][INTAKE] sender_user_id=123456789`
4. Add your user ID to `TELEGRAM_AUTH_USER_ID`:
   ```bash
   TELEGRAM_AUTH_USER_ID=123456789
   ```
   Or in `secrets/runtime.env`:
   ```
   TELEGRAM_AUTH_USER_ID=123456789
   ```
5. Restart the backend. Send `/help` in the direct chat — you should get a reply.

---

## Option B: Private Group (Recommended)

1. Create a new private group in Telegram (e.g. "ATP Control").
2. Add the ATP bot to the group.
3. Get the group chat ID:
   - Send a message in the group (e.g. `/help`)
   - Check backend logs: `[TG][INTAKE] chat_id=-1001234567890 chat_type=supergroup`
   - Or use [@getidsbot](https://t.me/getidsbot) — add it to the group, it will show the chat ID
   - Private supergroups typically have IDs like `-100xxxxxxxxxx`
4. Add the group chat ID to `TELEGRAM_AUTH_USER_ID` or `TELEGRAM_CHAT_ID`:
   ```bash
   TELEGRAM_AUTH_USER_ID=-1001234567890
   ```
   Or set as primary:
   ```bash
   TELEGRAM_CHAT_ID=-1001234567890
   ```
5. Restart the backend. Send `/help` in the group — you should get a reply.

---

## Multiple Operators

To allow both a direct chat and a group:

```bash
TELEGRAM_AUTH_USER_ID=-1001234567890,839853931
```

- `-1001234567890` = ATP Control group
- `839853931` = operator user ID (direct chat)

---

## Environment Variables

| Variable | Purpose |
|----------|---------|
| `TELEGRAM_CHAT_ID` | Primary command chat (ATP Control group or direct chat ID) |
| `TELEGRAM_AUTH_USER_ID` | Comma-separated list of authorized chat IDs and user IDs |
| `TELEGRAM_CHAT_ID_TRADING` | ATP Alerts — alerts only. Do NOT add to command auth. |

---

## Validation

1. Send `/help` in ATP Control — you should see the full command list.
2. Send `/runtime-check` — you should get runtime status.
3. Send `/investigate repeated BTC alerts` — you should get agent acknowledgment.
4. Check logs for `[TG][CHAT] chat_id=... chat_type=...` and `[TG][AUTH] decision=ALLOW`.

---

## Troubleshooting

| Symptom | Action |
|---------|--------|
| "⛔ Not authorized" | Add your chat_id or user_id to `TELEGRAM_AUTH_USER_ID` or `TELEGRAM_CHAT_ID` |
| "ATP Alerts is alerts-only" | You are in ATP Alerts. Use ATP Control instead. |
| No reply at all | Check `[TG][INTAKE]` in logs — if missing, bot may not be receiving updates |
