# Telegram Channel Routing & Authorization Validation Report

**Date:** 2025-03-19  
**Status:** Completed

---

## 1. Verified Inventory

| Logical Channel | Bot/Token Var | Chat ID Var | Modules Sending | Command Auth | Outbound Only | Config Verified |
|-----------------|---------------|-------------|-----------------|--------------|---------------|-----------------|
| **ATP Control** | TELEGRAM_ATP_CONTROL_BOT_TOKEN | TELEGRAM_ATP_CONTROL_CHAT_ID | claw_telegram, agent_telegram_approval, agent_telegram_policy, agent_task_executor, agent_anomaly_detector, task_health_monitor, notion_env, routes_github_webhook | Yes (TELEGRAM_ATP_CONTROL_CHAT_ID auto-added) | No | ⚠️ chat_id misconfigured (see below) |
| **AWS Alerts** | TELEGRAM_ALERT_BOT_TOKEN (fallback: TELEGRAM_BOT_TOKEN) | TELEGRAM_ALERT_CHAT_ID (fallback: TELEGRAM_CHAT_ID_OPS) | telegram_notifier (chat_destination=ops), system_alerts, infra/telegram_helper | No | Yes | ✅ |
| **Claw** | TELEGRAM_CLAW_BOT_TOKEN (fallback: TELEGRAM_BOT_TOKEN) | TELEGRAM_CLAW_CHAT_ID (fallback: TELEGRAM_CHAT_ID) | Command responses (telegram_commands replies to chat_id from update) | Yes (if chat in AUTHORIZED_USER_IDS) | No (commands) | ✅ |
| **ATP Alerts** | TELEGRAM_BOT_TOKEN | TELEGRAM_CHAT_ID_TRADING (fallback: TELEGRAM_CHAT_ID_AWS, TELEGRAM_CHAT_ID) | telegram_notifier (chat_destination=trading), signal_monitor, exchange_sync, daily_summary, sl_tp_checker, tp_sl_order_creator, scheduler, crypto_com_trade | No (alerts-only) | Yes | ✅ |

---

## 2. Authorization Audit

**File:** `backend/app/services/telegram_commands.py`  
**Function:** `_is_authorized(chat_id, user_id)` (lines 146–189)

### Authorization rules

1. `chat_id == AUTH_CHAT_ID` (TELEGRAM_CHAT_ID) → allow
2. `user_id in AUTHORIZED_USER_IDS` → allow
3. `chat_id in AUTHORIZED_USER_IDS` → allow

### AUTHORIZED_USER_IDS sources

| Source | When set |
|--------|----------|
| TELEGRAM_AUTH_USER_ID | Comma/space-separated list |
| TELEGRAM_CHAT_ID | Fallback when TELEGRAM_AUTH_USER_ID unset |
| TELEGRAM_ATP_CONTROL_CHAT_ID | Auto-added when set |

### Channel authorization status

| Channel | Authorized for commands | Reason |
|---------|-------------------------|--------|
| ATP Control | Yes | TELEGRAM_ATP_CONTROL_CHAT_ID auto-added to AUTHORIZED_USER_IDS |
| TELEGRAM_CHAT_ID | Yes | AUTH_CHAT_ID + always in AUTHORIZED_USER_IDS |
| TELEGRAM_AUTH_USER_ID entries | Yes | Explicit list |
| ATP Alerts (TELEGRAM_CHAT_ID_TRADING) | No | Explicitly excluded; "alerts-only" |
| AWS Alerts | No | Not in command auth; infra alerts only |

### Command polling bot

- **TELEGRAM_BOT_TOKEN** (or TELEGRAM_BOT_TOKEN_DEV locally) polls for updates
- **TELEGRAM_BOT_TOKEN** must be the bot whose commands are used (ATP Control or Claw for /menu)
- Commands reply to `chat_id` from the update (same chat)

---

## 3. Routing Audit

### Module → Category → Destination

| Module | Category | Destination | chat_destination / path |
|--------|----------|-------------|--------------------------|
| claw_telegram | DEV | ATP Control | TELEGRAM_ATP_CONTROL_* |
| agent_telegram_approval | DEV | ATP Control | send_claw_message |
| agent_telegram_policy | DEV | ATP Control | send_claw_message |
| agent_task_executor | DEV | ATP Control | send_claw_message, agent_telegram_approval |
| agent_anomaly_detector | DEV | ATP Control | claw_telegram |
| task_health_monitor | DEV | ATP Control | claw_telegram |
| notion_env | DEV | ATP Control | claw_telegram |
| routes_github_webhook | DEV | ATP Control | _send_telegram_message → claw_telegram |
| system_alerts | INFRA | AWS Alerts | telegram_notifier(chat_destination="ops") |
| telegram_notifier (ops) | INFRA | AWS Alerts | TELEGRAM_CHAT_ID_OPS |
| infra/telegram_helper | INFRA | AWS Alerts | TELEGRAM_ALERT_* or TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_OPS |
| telegram_commands | CONTROL | Reply to chat | chat_id from update |
| signal_monitor | TRADING | HiloVivo 3.0 | telegram_notifier (default trading) |
| exchange_sync | TRADING | HiloVivo 3.0 | telegram_notifier |
| daily_summary | TRADING | HiloVivo 3.0 | telegram_notifier |
| sl_tp_checker | TRADING | HiloVivo 3.0 | telegram_notifier |
| tp_sl_order_creator | TRADING | HiloVivo 3.0 | telegram_notifier |
| scheduler | TRADING | HiloVivo 3.0 | telegram_notifier |
| crypto_com_trade | TRADING | HiloVivo 3.0 | telegram_notifier |
| buy_index_monitor | TRADING | HiloVivo 3.0 | telegram_notifier |

### Routing vs desired

| Desired | Actual | Match |
|---------|--------|-------|
| DEV → ATP Control | claw_telegram → ATP Control | ✅ |
| INFRA → AWS Alerts | telegram_notifier(ops), system_alerts, infra/telegram_helper → AWS Alerts | ✅ |
| CONTROL → Claw | telegram_commands replies to chat_id from update | ✅ (responses go to user chat) |
| TRADING → HiloVivo 3.0 | telegram_notifier(trading) → HiloVivo 3.0 | ✅ |

---

## 4. Mismatches Identified

### 4.1 ATP Control: "bots can't send messages to bots"

**Test result:** `❌ ATP Control: FAILED - HTTP 403: Forbidden: bots can't send messages to bots`

**Cause:** `TELEGRAM_ATP_CONTROL_CHAT_ID` points to a **bot** instead of a **channel or group**.

**Fix:** Use a channel or group ID (negative, e.g. `-1001234567890`). See `docs/runbooks/ATP_CONTROL_TELEGRAM_FIX.md` Step 3.

### 4.2 No other routing mismatches

- DEV messages correctly route to ATP Control (claw_telegram)
- INFRA messages correctly route to AWS Alerts (telegram_notifier ops, system_alerts, infra/telegram_helper)
- TRADING messages correctly route to HiloVivo 3.0 (telegram_notifier trading)
- Command responses correctly reply to the requesting chat

---

## 5. Active Delivery Validation

**Script:** `scripts/validate_telegram_routing.py`

**Test messages sent:**

| Channel | Message | Expected | Result |
|---------|---------|----------|--------|
| ATP Control | [TEST][ATP_CONTROL] routing validation | ATP Control Alerts channel | ❌ FAILED (bots can't send to bots) |
| AWS Alerts | [TEST][AWS_ALERTS] routing validation | AWS_alerts channel | ✅ SENT |
| Claw | [TEST][CLAW] routing validation | Claw channel | ✅ SENT |
| HiloVivo 3.0 | [TEST][HILOVIVO30] routing validation | HiloVivo 3.0 channel | ✅ SENT |

**Where to check:** Each Telegram channel should show the corresponding test message. ATP Control will not show until `TELEGRAM_ATP_CONTROL_CHAT_ID` is fixed to a channel ID.

---

## 6. Callback/Command Behavior

| Item | Status |
|------|--------|
| Bot handling commands | TELEGRAM_BOT_TOKEN (telegram_commands polls) |
| Channels allowed for commands | TELEGRAM_CHAT_ID, TELEGRAM_AUTH_USER_ID, TELEGRAM_ATP_CONTROL_CHAT_ID |
| ATP Control Alerts authorized | Yes (when TELEGRAM_ATP_CONTROL_CHAT_ID set to channel) |
| ATP Alerts alerts-only | Yes (TELEGRAM_CHAT_ID_TRADING not in command auth) |
| Claw control-plane | Command responses go to chat_id from update; Claw channel receives if user sends from there |

---

## 7. Env Vars Used

| Var | Purpose |
|-----|---------|
| TELEGRAM_BOT_TOKEN | Main bot; commands polling + telegram_notifier (trading + ops) |
| TELEGRAM_CHAT_ID | Primary control; command auth |
| TELEGRAM_CHAT_ID_AWS | AWS fallback |
| TELEGRAM_CHAT_ID_OPS | AWS Alerts (ops) destination |
| TELEGRAM_CHAT_ID_TRADING | ATP Alerts (trading) destination |
| TELEGRAM_AUTH_USER_ID | Additional authorized user/channel IDs |
| TELEGRAM_ATP_CONTROL_BOT_TOKEN | ATP Control bot |
| TELEGRAM_ATP_CONTROL_CHAT_ID | ATP Control channel (must be channel, not bot) |
| TELEGRAM_ALERT_BOT_TOKEN | AWS Alerts bot (infra/telegram_helper) |
| TELEGRAM_ALERT_CHAT_ID | AWS Alerts channel |
| TELEGRAM_CLAW_BOT_TOKEN | Claw bot |
| TELEGRAM_CLAW_CHAT_ID | Claw channel |

---

## 8. Files Changed

| File | Change |
|------|--------|
| `scripts/validate_telegram_routing.py` | **Created** – validation script |
| `docs/audits/TELEGRAM_ROUTING_VALIDATION_REPORT.md` | **Created** – this report |

---

## 9. Unresolved / Ambiguous

| Item | Status |
|------|--------|
| TELEGRAM_ATP_CONTROL_CHAT_ID | Points to bot; must be channel ID. See `docs/runbooks/ATP_CONTROL_TELEGRAM_FIX.md` |
| TELEGRAM_ALERT_* | Not in secrets/runtime.env; validation used fallback (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID_OPS) |
| TELEGRAM_CLAW_* | Not in secrets/runtime.env; validation used fallback (TELEGRAM_BOT_TOKEN + TELEGRAM_CHAT_ID) |

---

## 10. Recommendations

1. **Fix ATP Control:** Set `TELEGRAM_ATP_CONTROL_CHAT_ID` to the ATP Control Alerts **channel** ID (not bot). Use @getidsbot or `getUpdates` to get the chat ID.
2. **Re-run validation:** `python scripts/validate_telegram_routing.py` after fixing.
3. **Verify in Telegram:** Confirm each channel shows the expected test message.
