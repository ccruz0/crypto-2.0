# Telegram Alerts Not Being Sent

**When to use:** Notion task "Investigate Telegram alerts not being sent" or when trading/signal alerts or health alerts are not reaching Telegram.

---

## 1. Run the diagnostic script (fastest path)

On the **same host as the backend** (or where the service that sends alerts runs):

```bash
cd /path/to/automated-trading-platform
# If using Docker for backend (e.g. on EC2 PROD):
docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_alerts.py
```

**From your machine via AWS SSM** (no SSH needed; requires AWS CLI and SSM access to PROD):

```bash
./scripts/diag/run_telegram_diagnostic_prod.sh
```

Optional: `INSTANCE_ID=i-xxx REGION=ap-southeast-1 ./scripts/diag/run_telegram_diagnostic_prod.sh`

**Or** start an SSM shell, then on the instance run:

```bash
cd ~/crypto-2.0  # or your repo path
docker compose --profile aws exec backend-aws python scripts/diagnose_telegram_alerts.py
```

The script checks: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `RUNTIME_ORIGIN`, `RUN_TELEGRAM`, `APP_ENV`, notifier enabled state, and optionally sends a test message. Follow the **FIXES NEEDED** section it prints.

---

## 2. Why sends are blocked (single source of truth)

All sends go through `TelegramNotifier.send_message()` in `backend/app/services/telegram_notifier.py`. Before any request to the Telegram API, `refresh_config()` runs. Sends are **blocked** when any of these are true:

| Block reason | Meaning | Fix |
|--------------|---------|-----|
| `run_telegram_disabled` | `RUN_TELEGRAM` is not truthy (1/true/yes/on) | Set `RUN_TELEGRAM=true` (or `1`) in env for the service (e.g. backend-aws, market-updater-aws). |
| `kill_switch_disabled` | DB setting `tg_enabled_aws` (or `tg_enabled_local`) is not `true` | Enable Telegram in dashboard/settings or set `trading_settings.setting_value = 'true'` for key `tg_enabled_aws`. |
| `token_missing` | No token for env: AWS → `TELEGRAM_BOT_TOKEN_AWS` or `TELEGRAM_BOT_TOKEN`; local → `TELEGRAM_BOT_TOKEN_LOCAL` or `TELEGRAM_BOT_TOKEN` | Set the right token in `.env.aws` / `secrets/runtime.env` / docker env. |
| `chat_id_missing` | No chat ID for env: AWS → `TELEGRAM_CHAT_ID_AWS` or `TELEGRAM_CHAT_ID`; local → same with `_LOCAL` fallback | Set the right chat ID in env. |
| `aws_using_local_credentials` | On AWS, generic or local credentials are used while LOCAL vars are also set (safety block) | Use only `TELEGRAM_*_AWS` (and optionally generic) on AWS; remove or avoid setting `TELEGRAM_*_LOCAL` on AWS. |

Blocked sends are logged with `[TG BLOCKED]` and the `reasons=` list. Search backend logs for that string to see the exact reason.

**Known bug (fixed 2026-03-14):** If diagnostic reports `NameError: name '_TELEGRAM_COOLDOWN_UNTIL_TS' is not defined`, ensure `telegram_notifier.py` has the module-level `_TELEGRAM_COOLDOWN_UNTIL_TS: Optional[float] = None` declaration. Without it, all sends crash before reaching the Telegram API.

---

## 3. Alerts that use “origin” (e.g. signal monitor)

Trading/signal alerts call `send_message(..., origin=...)`. Only **origin `"AWS"`** actually sends to Telegram; other origins are blocked and logged.

- **Origin** is set from `get_runtime_origin()` (see `backend/app/core/runtime.py`), which typically uses `RUNTIME_ORIGIN` or `ENVIRONMENT`.
- The service that **emits** the alert (e.g. **market-updater-aws** for live signals) must have `RUNTIME_ORIGIN=AWS` (or equivalent so `get_runtime_origin()` returns `"AWS"`).

**Check:** In `docker-compose*.yml` (or wherever the emitting service is defined), ensure that service has `RUNTIME_ORIGIN: "AWS"` and `ENVIRONMENT: "aws"` if your runtime logic uses it.

---

## 4. Health snapshot → Telegram (cron script)

Health alerts are sent by **`scripts/diag/health_snapshot_telegram_alert.sh`**, not by the backend. That script:

- Reads Telegram credentials from repo `.env` / `.env.aws` / `secrets/runtime.env`.
- Sends via `curl` to `https://api.telegram.org/bot.../sendMessage`.
- Then POSTs the same snapshot to `POST $BASE/api/monitoring/health-alert` to create a Notion task (backend).

If **health** alerts don’t reach Telegram:

- Confirm the script runs (cron/systemd) and that `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are set in the env it uses (or `TELEGRAM_BOT_TOKEN_ENCRYPTED` and decryption works).
- Confirm the script can reach the Telegram API (network/firewall).

If the **Notion task** for the health alert is not created, the backend may be down or `NOTION_API_KEY` / `NOTION_TASK_DB` not set; see [ATP_HEALTH_ALERT_STREAK_FAIL.md](ATP_HEALTH_ALERT_STREAK_FAIL.md).

---

## 5. Relevant code and docs

| What | Where |
|------|--------|
| Send guard & block reasons | `backend/app/services/telegram_notifier.py` → `refresh_config()`, `send_message()` |
| Runtime origin | `backend/app/core/runtime.py` → `get_runtime_origin()` |
| Central alert emission | `backend/app/services/alert_emitter.py` → `emit_alert()` → `telegram_notifier.send_*_signal()` |
| Telegram AWS setup | [docs/TELEGRAM_AWS_RUNBOOK.md](../TELEGRAM_AWS_RUNBOOK.md) |
| Telegram pipelines / diagnostics | [docs/monitoring/TELEGRAM_PIPELINES.md](../monitoring/TELEGRAM_PIPELINES.md), [docs/monitoring/TELEGRAM_DIAGNOSTICS_REPORT.md](../monitoring/TELEGRAM_DIAGNOSTICS_REPORT.md) |

---

## 6. Alerts going to the wrong chat

**Symptom:** Alerts send successfully but arrive in a private chat instead of the target channel (e.g. "Hilovivo-alerts").

**Cause:** `TELEGRAM_CHAT_ID` is set to a private chat ID (positive, e.g. `839853931`) instead of the channel ID (negative, e.g. `-1001234567890`).

**Routing:** Separate channels for trading vs ops:
- **ATP Alerts** (trading): `TELEGRAM_CHAT_ID` / `TELEGRAM_CHAT_ID_TRADING` — signals, orders, reports
- **AWS_alerts** (ops): `TELEGRAM_CHAT_ID_OPS` — health, anomalies, scheduler
See [TELEGRAM_CHANNEL_ROUTING.md](TELEGRAM_CHANNEL_ROUTING.md).

**Fix:**

1. **Get the correct channel chat ID** (negative number):
   - **Option A (recommended):** Post a message in the target channel, then run:
     ```bash
     ./scripts/diag/run_get_channel_id_prod.sh
     ```
     This uses the PROD bot token and prints all channel/group IDs from recent updates.
   - **Option B:** Forward a message from the channel to @getidsbot (not @userinfobot — that shows the *sender*, not the chat).
   - **Option C:** `curl "https://api.telegram.org/bot${TOKEN}/getUpdates" | jq '.result[] | .channel_post.chat // .message.chat | select(.id < 0)'`

2. **Update and apply** (from your machine, with AWS CLI):
   ```bash
   # Trading channel (HILOVIVO3.0)
   TELEGRAM_CHAT_ID=-1001234567890 ./scripts/aws/update_telegram_chat_id.sh
   # Ops channel (AWS_alerts)
   TELEGRAM_CHAT_ID_OPS=-1009876543210 ./scripts/aws/update_telegram_chat_id_ops.sh
   ```
   This updates SSM parameters, re-renders `secrets/runtime.env` on PROD, and restarts the backend.

3. **Manual alternative** (if no AWS CLI or SSM):
   - Edit `.env.aws` on the server: set `TELEGRAM_CHAT_ID_AWS` or `TELEGRAM_CHAT_ID` to the channel ID.
   - Run `scripts/aws/render_runtime_env.sh` on the server.
   - Restart: `docker compose --profile aws restart backend-aws`.

See also: [docs/monitoring/telegram_channel_id_fix.md](../monitoring/telegram_channel_id_fix.md).

---

## 7. Resolving the Notion task

- **If you fixed config:** Re-run `diagnose_telegram_alerts.py` (and optionally trigger a test alert); then set the Notion task status to **Testing** or **Done** and add a short comment (e.g. “Fixed: RUN_TELEGRAM was unset on backend-aws”).
- **If you identified a non-config cause** (e.g. bug, network, or product decision): Document the finding in the task, update this runbook if needed, and set status to **Done** or **Won’t fix** with the reason.
