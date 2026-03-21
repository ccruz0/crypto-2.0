# ATP Control Telegram Fix

**Error:** `Forbidden: bots can't send messages to bots`

**Cause:** `TELEGRAM_ATP_CONTROL_CHAT_ID` points to a **bot** instead of a **channel or group**. Bots can only send messages to channels, groups, or users—not to other bots.

---

## Step 1: Create or Choose a Channel/Group

You need a **Telegram channel or group** for ATP Control messages (tasks, approvals, investigations).

**Option A – New channel**
1. Open Telegram → Menu → New Channel
2. Name it (e.g. "ATP Control" or "ATP Dev")
3. Choose: Public or Private
4. Create the channel

**Option B – Existing group**
- Use any existing group where you want ATP Control alerts.

---

## Step 2: Add @ATP_control_bot to the Channel/Group

1. Open the channel/group
2. Go to channel/group info (tap the name at the top)
3. **Add members** or **Administrators**
4. Search for `@ATP_control_bot`
5. Add it as **Administrator** (needed so it can post)
6. Enable permissions: **Post messages**, **Edit messages** (if you want)

---

## Step 3: Get the Chat ID

The chat ID must be a **channel or group** ID (usually negative, e.g. `-1001234567890`), not a bot ID.

### Method A: Using @getidsbot (recommended)

1. Add [@getidsbot](https://t.me/getidsbot) to your channel/group, or message it in a private chat
2. **Forward a message** from your ATP Control channel to @getidsbot
3. Or send any message in the channel and forward it to @getidsbot
4. It will reply with the channel’s **chat ID** (e.g. `-1001234567890`)

### Method B: Using getUpdates

1. **Post a message** in the ATP Control channel (e.g. "test" or "/start")
2. Run (replace `YOUR_ATP_CONTROL_TOKEN` with your token):

   ```bash
   curl -s "https://api.telegram.org/botYOUR_ATP_CONTROL_TOKEN/getUpdates?limit=10" | python3 -m json.tool
   ```

3. In the JSON, find `"chat":{"id":-1001234567890,...}` — the `id` is your chat ID
4. Channel IDs are usually negative (e.g. `-1001234567890`)

**Note:** If the bot has a webhook, `getUpdates` may be empty. Use Method A (@getidsbot) in that case.

### Method C: Using the repo script

```bash
cd ~/automated-trading-platform
TELEGRAM_BOT_TOKEN=YOUR_ATP_CONTROL_TOKEN ./scripts/diag/get_chat_ids_local.sh
```

Post a message in the channel first, then run this. It lists chat IDs from recent updates.

---

## Step 4: Save the Token and Chat ID

### Local / secrets

```bash
./scripts/setup_atp_control_token_popup.sh
```

Or edit `secrets/runtime.env`:

```bash
TELEGRAM_ATP_CONTROL_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_ATP_CONTROL_CHAT_ID=-1001234567890
```

### AWS (Production)

Use SSM or your runtime env:

```bash
# Add to secrets/runtime.env on EC2, or:
aws ssm put-parameter --name "/automated-trading-platform/prod/telegram/atp_control_bot_token" \
  --value "YOUR_TOKEN" --type SecureString --overwrite
aws ssm put-parameter --name "/automated-trading-platform/prod/telegram/atp_control_chat_id" \
  --value "-1001234567890" --type SecureString --overwrite
```

Then ensure `render_runtime_env.sh` (or your deployment) reads these and sets:

- `TELEGRAM_ATP_CONTROL_BOT_TOKEN`
- `TELEGRAM_ATP_CONTROL_CHAT_ID`

---

## Step 5: Verify

```bash
python3 scripts/send_channel_descriptions.py
```

Expected output:

```
✅ ATP Control: sent to @ATP_control_bot
```

---

## "Not authorised" / "⛔ Not authorized"

If you get **"Not authorised"** when sending commands (e.g. /menu, /task) to the bot:

### Cause

The backend only accepts commands from chats/users listed in `TELEGRAM_CHAT_ID`, `TELEGRAM_AUTH_USER_ID`, or `TELEGRAM_ATP_CONTROL_CHAT_ID`. Your channel or user ID is not in that list.

### Fix

**Option 1: Use TELEGRAM_ATP_CONTROL_CHAT_ID (recommended for ATP Control channel)**

If you use the **ATP Control Alerts** channel for both outbound alerts and commands, set:

```bash
TELEGRAM_ATP_CONTROL_BOT_TOKEN=123456789:ABCdef...
TELEGRAM_ATP_CONTROL_CHAT_ID=-1001234567890   # ATP Control Alerts channel ID
```

The backend **auto-authorizes** `TELEGRAM_ATP_CONTROL_CHAT_ID` for commands—no need to add it to `TELEGRAM_CHAT_ID` or `TELEGRAM_AUTH_USER_ID`. Ensure `TELEGRAM_BOT_TOKEN` is the ATP Control bot token so commands are polled from that bot.

**Option 2: Add your channel to TELEGRAM_CHAT_ID**

If you use the ATP Control **channel** for commands and prefer the legacy config:

```bash
TELEGRAM_CHAT_ID=-1001234567890   # Your ATP Control channel ID
```

in `secrets/runtime.env` or `.env.aws`.

**Option 3: Add your user ID to TELEGRAM_AUTH_USER_ID**

If you use **private chat** with the bot:

1. Get your Telegram user ID: message [@userinfobot](https://t.me/userinfobot) — it replies with your ID
2. Add to env:
   ```bash
   TELEGRAM_AUTH_USER_ID=123456789
   ```
   For multiple users/channels: `TELEGRAM_AUTH_USER_ID=123456789,-1001234567890`

**Option 4: Add the ATP Control channel ID to TELEGRAM_AUTH_USER_ID**

```bash
TELEGRAM_AUTH_USER_ID=-1001234567890   # ATP Control channel ID
```

### Which bot handles commands?

The backend polls **one** bot (`TELEGRAM_BOT_TOKEN`). Commands only work when you message **that** bot. For /menu and /task in the ATP Control channel:

- Use the **ATP Control bot token** for `TELEGRAM_BOT_TOKEN`
- Set `TELEGRAM_ATP_CONTROL_CHAT_ID` (auto-authorized), or `TELEGRAM_CHAT_ID`, or `TELEGRAM_AUTH_USER_ID` to your ATP Control channel ID

---

## Telegram API "Unauthorized" (401)

If you get **401 Unauthorized** when sending a test message:

- **Invalid token** — Token is wrong or revoked. Get a new token from [@BotFather](https://t.me/BotFather) for @ATP_control_bot.
- **Wrong bot** — Ensure you use the token for @ATP_control_bot, not another bot.

---

## Common Mistakes

| Mistake | Fix |
|--------|-----|
| Chat ID is a bot ID | Use a channel or group ID (negative number) |
| Chat ID is a user ID | Use a channel or group ID (negative number) |
| Bot not added to channel | Add @ATP_control_bot as admin in the channel |
| Bot not admin | Promote it to admin so it can post |
| Wrong token | Use the token for @ATP_control_bot from @BotFather |
| "Not authorised" on /menu | Set TELEGRAM_ATP_CONTROL_CHAT_ID (auto-authorized), or add to TELEGRAM_CHAT_ID / TELEGRAM_AUTH_USER_ID |

---

## Quick Reference

| Item | Value |
|------|-------|
| Bot | @ATP_control_bot |
| Env vars | `TELEGRAM_ATP_CONTROL_BOT_TOKEN`, `TELEGRAM_ATP_CONTROL_CHAT_ID` |
| Chat ID format | Negative number, e.g. `-1001234567890` |
| Get chat ID | @getidsbot or `getUpdates` |
