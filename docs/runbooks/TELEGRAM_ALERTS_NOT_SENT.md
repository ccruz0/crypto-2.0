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
cd ~/automated-trading-platform  # or your repo path
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

## 6. Resolving the Notion task

- **If you fixed config:** Re-run `diagnose_telegram_alerts.py` (and optionally trigger a test alert); then set the Notion task status to **Testing** or **Done** and add a short comment (e.g. “Fixed: RUN_TELEGRAM was unset on backend-aws”).
- **If you identified a non-config cause** (e.g. bug, network, or product decision): Document the finding in the task, update this runbook if needed, and set status to **Done** or **Won’t fix** with the reason.
