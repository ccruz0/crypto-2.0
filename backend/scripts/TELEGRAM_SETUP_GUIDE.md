# Telegram Bot Setup Guide for Local Testing

## ⚠️ Important: Use DEV Bot for Local Testing

**AWS production uses the production bot token and actively polls `getUpdates` with long polling.**
**Using the same token locally will cause 409 conflicts.**

**Solution**: Use a **separate DEV bot** for local testing.

---

## Local DEV Bot Quickstart

The fastest way to set up local Telegram testing:

### Step 1: Create Dev Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow instructions
3. Choose a name (e.g., "ATP Local Dev Bot")
4. Choose a username (e.g., `@atp_local_dev_bot`)
5. **Copy the token** (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Bootstrap Setup

```bash
cd /Users/carloscruz/automated-trading-platform/backend
export TELEGRAM_BOT_TOKEN_DEV="your_dev_bot_token_here"
python3 scripts/local_dev_telegram_bootstrap.sh
```

**What it does:**
- Verifies DEV token is set
- Extracts chat_id from your dev bot (you must send a message first)
- Tests sendMessage to confirm it works
- Prints export commands for your shell

**Expected output:**
```
🔍 Using DEV bot token: 123456...wxyz

📱 Step 1: Extracting chat_id from dev bot...
   💡 Make sure you've sent a message to your dev bot in Telegram first!

✅ Found chat_id: 123456789

📤 Step 2: Testing sendMessage with dev bot...
✅ SUCCESS: Message sent (message_id: 123)

✅ SUCCESS: Local dev bot is configured and working!

📋 Copy these lines into your shell:

export TELEGRAM_BOT_TOKEN_DEV="your_token"
export TELEGRAM_CHAT_ID_DEV="123456789"
```

### Step 3: Run End-to-End Test

```bash
cd /Users/carloscruz/automated-trading-platform/backend
export TELEGRAM_BOT_TOKEN_DEV="your_token"
export TELEGRAM_CHAT_ID_DEV="your_chat_id"
python3 scripts/local_e2e_alert_test.sh
```

**What it does:**
- Starts backend (or uses existing instance)
- Triggers test alert (BTC_USDT BUY)
- Checks logs for `[TELEGRAM_RESPONSE] status=200` and `[TELEGRAM_SUCCESS]`
- Queries database for alert persistence
- Verifies `blocked=false` in latest row

**Expected output:**
```
🧪 End-to-End Alert Test
========================

✅ Alert triggered successfully
✅ [TELEGRAM_RESPONSE] status=200 found
✅ [TELEGRAM_SUCCESS] found
✅ SUCCESS: Latest alert shows blocked=False
```

### Troubleshooting

**If bootstrap script fails:**
- Make sure you sent a message to your dev bot in Telegram first
- Check that `TELEGRAM_BOT_TOKEN_DEV` is set correctly
- Verify bot token is valid (try sending a message manually)

**If e2e test shows 409 conflict:**
- AWS backend might still be running. Stop it: `./stop_backend_aws.sh`
- Or use a completely different bot token (not the production one)

**If logs show status != 200:**
- Check `TELEGRAM_CHAT_ID_DEV` is correct
- Verify you sent a message to the dev bot (not production bot)
- Check bot token matches the bot you're messaging

---

## Local Bot Setup (Recommended: Avoid 409 Conflicts)

To avoid 409 conflicts with AWS production, use a **separate dev bot** for local testing.

### Step 1: Create Dev Bot

1. Open Telegram and search for [@BotFather](https://t.me/botfather)
2. Send `/newbot` and follow instructions
3. Choose a name (e.g., "ATP Local Dev Bot")
4. Choose a username (e.g., `@atp_local_dev_bot`)
5. **Copy the token** (format: `123456789:ABCdefGHIjklMNOpqrsTUVwxyz`)

### Step 2: Set Environment Variables

```bash
export TELEGRAM_BOT_TOKEN_DEV="your_dev_bot_token_here"
# Chat ID will be extracted in next step
```

### Step 3: Extract Chat ID

1. **Send a message to your dev bot** in Telegram:
   - Search for your dev bot (e.g., `@atp_local_dev_bot`)
   - Press "Start" or send `/start`
   - Send a test message: `ping`

2. **Run the diagnostic script:**
   ```bash
   cd /Users/carloscruz/automated-trading-platform/backend
   export TELEGRAM_BOT_TOKEN_DEV="your_dev_bot_token"
   python3 scripts/telegram_chat_id_doctor.py
   ```

3. **Copy the chat_id** from output:
   ```
   USE_THIS_CHAT_ID=123456789
   ```

4. **Set chat_id:**
   ```bash
   export TELEGRAM_CHAT_ID_DEV="123456789"
   ```

### Step 4: Test Direct Send

```bash
python3 scripts/telegram_send_test.py
```

Expected: `✅ SUCCESS: Message sent (message_id: ...)`

### Step 5: Run End-to-End Test

```bash
# Terminal 1: Start backend
cd /Users/carloscruz/automated-trading-platform/backend
export DATABASE_URL="postgresql://trader:traderpass@localhost:5432/atp"
export ENVIRONMENT="local"
export RUN_TELEGRAM="true"
export TELEGRAM_BOT_TOKEN_LOCAL="$TELEGRAM_BOT_TOKEN_DEV"
export TELEGRAM_CHAT_ID_LOCAL="$TELEGRAM_CHAT_ID_DEV"
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# Terminal 2: Trigger alert
curl -sS -X POST http://localhost:8002/api/test/simulate-alert \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC_USDT","signal_type":"BUY"}' | python3 -m json.tool
```

### Step 6: Verify Success

Check logs for:
- `[TELEGRAM_RESPONSE] status=200`
- `[TELEGRAM_SUCCESS] message_id=...`

Check DB:
```bash
python3 <<'PY'
import os
from sqlalchemy import create_engine, text
engine=create_engine("postgresql://trader:traderpass@localhost:5432/atp", future=True)
q=text("SELECT id, symbol, blocked, throttle_status FROM telegram_messages WHERE symbol='BTC_USDT' ORDER BY timestamp DESC LIMIT 1")
with engine.connect() as c:
    r = c.execute(q).fetchone()
    if r:
        print(f"Latest: ID={r[0]}, Blocked={r[2]}, Status={r[3]}")
PY
```

Expected: `Blocked=False, Status=SUCCESS` (or not FAILED)

---

## Problem: getUpdates Returns Empty or 409 Conflict

### Root Causes

1. **No messages received**: Bot hasn't received any messages from your account
2. **409 Conflict**: Another instance (backend/uvicorn) is polling getUpdates
3. **Webhook configured**: Webhooks block getUpdates (script handles this automatically)

## Solution: Manual Chat ID Extraction

### Step 1: Interact with Bot in Telegram

1. Open Telegram (desktop or mobile app)
2. Search for: `@HILOVIVO30_bot`
3. Press **"Start"** or send `/start`
4. Send a test message: `ping` or `test`

### Step 2: Wait for Conflict to Clear (if 409)

If you see "409 Conflict" errors:
- Wait **30-60 seconds** after stopping all backend processes
- The conflict usually clears automatically
- Or use the alternative method below

### Step 3: Extract Chat ID

**Option A: Use the diagnostic script (recommended)**

```bash
cd /Users/carloscruz/automated-trading-platform/backend
export TELEGRAM_BOT_TOKEN_LOCAL="your_token"
python3 scripts/telegram_chat_id_doctor.py
```

Look for: `USE_THIS_CHAT_ID=...`

**Option B: Manual curl (if script fails)**

```bash
export TELEGRAM_BOT_TOKEN_LOCAL="your_token"
curl -sS "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN_LOCAL}/getUpdates" | python3 <<'PY'
import sys, json
d = json.load(sys.stdin)
res = d.get("result", [])
if res:
    for u in reversed(res):
        m = u.get("message") or u.get("edited_message") or {}
        if m.get("chat"):
            chat_id = m["chat"].get("id")
            if chat_id:
                print(f"Chat ID: {chat_id}")
                print(f"Type: {m['chat'].get('type')}")
                break
else:
    print("No messages found. Send a message to the bot first.")
PY
```

### Step 4: Test Direct Send

```bash
export TELEGRAM_CHAT_ID_LOCAL="<extracted_chat_id>"
python3 scripts/telegram_send_test.py
```

Expected: `✅ SUCCESS: Message sent (message_id: ...)`

### Step 5: Run End-to-End Test

```bash
# Terminal 1: Start backend
cd /Users/carloscruz/automated-trading-platform/backend
export DATABASE_URL="postgresql://trader:traderpass@localhost:5432/atp"
export ENVIRONMENT="local"
export TELEGRAM_BOT_TOKEN_LOCAL="your_token"
export TELEGRAM_CHAT_ID_LOCAL="<valid_chat_id>"
python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002

# Terminal 2: Trigger alert
curl -sS -X POST http://localhost:8002/api/test/simulate-alert \
  -H "Content-Type: application/json" \
  -d '{"symbol":"BTC_USDT","signal_type":"BUY"}' | python3 -m json.tool

# Terminal 2: Check DB
python3 <<'PY'
import os
from sqlalchemy import create_engine, text
engine=create_engine("postgresql://trader:traderpass@localhost:5432/atp", future=True)
q=text("SELECT id, symbol, blocked, throttle_status FROM telegram_messages WHERE symbol='BTC_USDT' ORDER BY timestamp DESC LIMIT 1")
with engine.connect() as c:
    r = c.execute(q).fetchone()
    if r:
        print(f"Latest: ID={r[0]}, Blocked={r[2]}, Status={r[3]}")
PY
```

## Troubleshooting

### 409 Conflict Persists

1. Check for running backend:
   ```bash
   ps aux | grep uvicorn | grep -v grep
   ```
2. Kill all instances:
   ```bash
   pkill -f "uvicorn app.main:app"
   ```
3. Wait 60 seconds, then rerun script

### "chat not found" Error

- Chat ID is invalid or bot was blocked
- Extract a fresh chat_id using Step 3
- Ensure you sent a message to the bot first

### No Updates After Sending Message

- Check bot username: `@HILOVIVO30_bot`
- Ensure you're using the correct token
- Try sending another message and wait 5 seconds

## Security Notes

- **Never paste full tokens** in chat/email
- Tokens are automatically masked in script output
- Rotate tokens if accidentally exposed (via @BotFather)
