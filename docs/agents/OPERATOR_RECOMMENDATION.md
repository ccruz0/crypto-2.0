# Telegram Operator Recommendation — Final

**Version:** 1.0  
**Date:** 2026-03-15

---

## Summary

**Use ATP Control (private group or direct chat) for all interactive commands.** HILOVIVO3.0 is alerts-only and is not reliable for command/reply workflows.

---

## Operator Model

| Context | Role | Commands? |
|---------|------|-----------|
| **ATP Control** | Command/control interface | Yes — `/help`, `/runtime-check`, `/investigate`, `/agent`, etc. |
| **HILOVIVO3.0** | Alerts-only channel | No |
| **AWS_alerts** | Technical alerts channel | No |
| **Claw** | OpenClaw-native only | OpenClaw commands only (`/new`, `/reset`, `/status`, `/context`) |

---

## Setup Steps

1. Create a private Telegram group (e.g. "ATP Control") or use direct chat with the bot.
2. Add the ATP bot to the group.
3. Get the group chat ID:
   - Send a message in the group (e.g. `/help`)
   - Check backend logs: `[TG][INTAKE] chat_id=-1001234567890 chat_type=supergroup`
   - Or use [@getidsbot](https://t.me/getidsbot) in the group
4. Add the chat ID to `TELEGRAM_AUTH_USER_ID` or `TELEGRAM_CHAT_ID`:
   ```bash
   TELEGRAM_AUTH_USER_ID=-1001234567890
   ```
   Or for multiple operators:
   ```bash
   TELEGRAM_AUTH_USER_ID=-1001234567890,839853931
   ```
5. Restart the backend. See [ATP_CONTROL_SETUP.md](ATP_CONTROL_SETUP.md) for details.

---

## Validation Steps

After setup, run these tests in ATP Control:

| # | Command | Expected |
|---|---------|----------|
| 1 | `/help` | Full command list with channel roles |
| 2 | `/runtime-check` | Runtime status (pydantic, etc.) |
| 3 | `/investigate repeated BTC alerts` | Task received, agent selected |
| 4 | `/agent sentinel investigate repeated BTC alerts` | Task received, Sentinel |

**Log checks:**

- `[TG][CHAT] chat_id=... chat_type=...` — incoming command source
- `[TG][AUTH] decision=ALLOW`
- `[TG][CMD] handler=...` — command dispatched

**If you send a command in HILOVIVO3.0:**

- Expect: "HILOVIVO3.0 is alerts-only. Use ATP Control (private group or direct chat) for commands."
- Logs: `[TG][AUTH] decision=DENY`

---

## Why Not HILOVIVO3.0 for Commands?

- Channels use `channel_post`; interactive command/reply workflows are unreliable in channels
- Bot may not receive all channel posts depending on admin status and Telegram behavior
- Private groups and direct chats use `message` and provide reliable two-way communication

---

## Related Docs

- [ATP_CONTROL_SETUP.md](ATP_CONTROL_SETUP.md) — setup guide
- [AGENT_OPERATING_MODEL.md](AGENT_OPERATING_MODEL.md) — channel responsibilities
- [TELEGRAM_AGENT_COMMANDS.md](TELEGRAM_AGENT_COMMANDS.md) — command reference
