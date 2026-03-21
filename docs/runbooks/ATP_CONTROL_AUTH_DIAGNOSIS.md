# ATP Control Authorization Diagnosis

**Symptom:** Bot receives messages from the new Telegram channel but replies with "⛔ Not authorized".

---

## 1. Auth Check Location

| Item | Value |
|------|-------|
| **File** | `backend/app/services/telegram_commands.py` |
| **Function** | `_is_authorized(chat_id, user_id)` (lines ~146–189) |
| **Called from** | Text commands (line ~5011), callback queries (line ~4525), menu handlers |
| **Response** | `send_command_response(chat_id, "⛔ Not authorized")` |

---

## 2. Authorization Logic

A message is allowed if any of these match:

1. `chat_id == AUTH_CHAT_ID` (from `TELEGRAM_CHAT_ID`)
2. `user_id in AUTHORIZED_USER_IDS`
3. `chat_id in AUTHORIZED_USER_IDS`

`AUTHORIZED_USER_IDS` is built from:

- `TELEGRAM_AUTH_USER_ID` (comma/space-separated)
- `TELEGRAM_CHAT_ID` (if `TELEGRAM_AUTH_USER_ID` is unset)
- `TELEGRAM_ATP_CONTROL_CHAT_ID` (auto-added when set)

---

## 3. Get the Actual Chat ID

Diagnostic logging was added. When auth fails, logs include:

```
[TG][AUTH][DENY] chat_id=... chat_type=... chat_title=... chat_username=...
TELEGRAM_ATP_CONTROL_CHAT_ID=... AUTHORIZED_USER_IDS=...
```

**Steps:**

1. Restart the backend (so new logging is active).
2. Send `/menu` (or any command) from the new ATP Control channel.
3. Inspect logs for `[TG][AUTH][DENY]`.
4. Use the logged `chat_id` as the value to authorize.

---

## 4. Config Variables

| Variable | Purpose |
|----------|---------|
| `TELEGRAM_ATP_CONTROL_CHAT_ID` | ATP Control Alerts channel; auto-authorized when set |
| `TELEGRAM_CHAT_ID` | Primary control channel |
| `TELEGRAM_AUTH_USER_ID` | Comma-separated user/channel IDs |
| `TELEGRAM_BOT_TOKEN` | Bot token used for polling (must be ATP Control bot) |

---

## 5. Minimal Fix

**Option A (recommended):** Set `TELEGRAM_ATP_CONTROL_CHAT_ID` to the channel ID from the logs.

```bash
# In secrets/runtime.env or .env.aws
TELEGRAM_ATP_CONTROL_CHAT_ID=-1001234567890   # Use actual chat_id from [TG][AUTH][DENY] log
```

Restart the backend. The channel is auto-authorized.

**Option B:** Add the channel ID to `TELEGRAM_AUTH_USER_ID`:

```bash
TELEGRAM_AUTH_USER_ID=-1001234567890,other_id   # Append your channel ID
```

**Option C:** Use the channel as the primary control chat:

```bash
TELEGRAM_CHAT_ID=-1001234567890
```

---

## 6. Startup Check

On startup, logs show:

```
[TG][CONFIG] command_intake: ... atp_control_chat_id=-1001234567890 authorized_count=N
```

If `atp_control_chat_id=none`, `TELEGRAM_ATP_CONTROL_CHAT_ID` is not set.

---

## 7. Common Causes

| Cause | Fix |
|-------|-----|
| `TELEGRAM_ATP_CONTROL_CHAT_ID` not set | Set it to the channel ID from logs |
| Wrong chat ID format | Use the exact value from `[TG][AUTH][DENY]` (e.g. `-1001234567890`) |
| Wrong bot token | `TELEGRAM_BOT_TOKEN` must be the ATP Control bot token |
| Backend not restarted | Restart after changing env vars |

---

## 8. Complete Authorization Flow

### Env Files by Environment

| Environment | Env File | Notes |
|-------------|----------|-------|
| **Local** | `secrets/runtime.env` | Used by backend-dev, backend (profile local) |
| **AWS** | `.env.aws` → `secrets/runtime.env` | `render_runtime_env.sh` reads .env.aws and writes runtime.env |
| **AWS (SSM)** | SSM Parameter Store | `/automated-trading-platform/prod/telegram/atp_control_chat_id` |

### Step-by-Step Fix

1. **Get chat_id from logs** (after sending `/menu` from ATP Control Alerts):
   ```bash
   ./scripts/extract_atp_control_chat_id_from_logs.sh
   ```
   Or manually: `./scripts/add_atp_control_chat_id.sh -1001234567890` (use actual chat_id from logs)

2. **Restart backend:**
   - AWS: `docker compose --profile aws restart backend-aws`
   - Local: `docker compose --profile local restart backend-dev`

3. **For AWS (.env.aws):** Add to `.env.aws` on EC2, then re-render and restart:
   ```bash
   echo "TELEGRAM_ATP_CONTROL_CHAT_ID=-1001234567890" >> .env.aws   # use actual chat_id
   bash scripts/aws/render_runtime_env.sh
   docker compose --profile aws restart backend-aws
   ```

4. **Validate:** Send `/menu` from ATP Control Alerts channel. Bot should show main menu (not "Not authorized").

---

## 9. Final Authorized Channel Mapping

| Channel | Env Var | Purpose |
|---------|---------|---------|
| ATP Control Alerts | `TELEGRAM_ATP_CONTROL_CHAT_ID` | Tasks, approvals, investigations, agent logs; auto-authorized for commands |
| Primary control | `TELEGRAM_CHAT_ID` | Legacy primary; also in AUTHORIZED_USER_IDS |
| Additional | `TELEGRAM_AUTH_USER_ID` | Comma-separated user/channel IDs |
| ATP Alerts | `TELEGRAM_CHAT_ID_TRADING` | Alerts-only; NOT authorized for commands |
