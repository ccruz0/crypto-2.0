## 1. Summary

Production experienced duplicate Telegram command/callback handling caused by multiple runtimes consuming updates for the same bot token. Impact included duplicated task actions, callback confusion, and intermittent user-facing unknown-command responses. The incident was resolved by token rotation, poller cleanup, and runtime restart, with post-fix validation confirming stable single-consumer behavior.

## 2. Symptoms

- `getUpdates conflict (409)` in backend logs.
- `[TG] Another poller is active, cannot acquire lock` warnings.
- Duplicate task execution behavior from Telegram-triggered flows.
- User-facing callback error text, including `Unknown command: task_project:atp`.
- Intermittent `Unknown command. Use /help.` during callback-driven workflows.

## 3. Root Cause

The same Telegram bot token was active across more than one runtime (PROD + LAB and/or external stale consumer). Telegram long polling allows only one effective consumer stream per bot token; concurrent pollers create API conflicts and race conditions. This caused:

- `409` conflicts from Telegram API.
- advisory lock contention in internal poller logic.
- mixed/duplicate handling paths where one consumer processed the intended callback while another runtime handled stale/partial context, producing unknown-command responses.

## 4. Investigation Steps

1. Inspected live backend logs for conflict signatures (`409`, duplicate poller warnings, unknown-command events).
2. Enumerated active consumers and token-bearing runtimes across PROD, LAB, and local.
3. Correlated token source configuration and runtime process/container state.
4. Verified callback/message routing paths in `backend/app/services/telegram_commands.py`.
5. Added temporary high-signal tracing in `handle_telegram_update` to prove branch selection and return paths during live callback processing.
6. Recreated only the live backend container and repeated correlation to isolate active source.

## 5. Resolution

1. Rotated ATP Control bot token via BotFather (`/revoke` for `@ATP_control_bot`) and generated a new token.
2. Updated AWS SSM SecureString:
   - `/automated-trading-platform/prod/telegram/bot_token`
3. Updated runtime secret source (`secrets/runtime.env`) so PROD reads the new token.
4. Removed/scrubbed non-PROD consumers from the active token path (LAB/external overlap eliminated).
5. Restarted/recreated PROD backend container:
   - `docker compose --profile aws up -d --force-recreate backend-aws`
6. Confirmed only one effective poller remained active for the new token.

## 6. Validation

Validation criteria and checks:

- Backend health:
  - `docker compose --profile aws ps backend-aws`
- Conflict scan:
  - `docker compose --profile aws logs backend-aws --tail=500 | grep -E 'getUpdates conflict|Another poller is active|duplicate_telegram_poller_suspected'`
- Unknown-command scan:
  - `docker compose --profile aws logs backend-aws --tail=500 | grep -E 'Unknown command|task_project:atp'`
- Functional flow:
  - Send `/task <description>`, click project callback (`task_project:atp`), verify single task creation and no duplicate/unknown responses.

Post-resolution result: no recurring `409`, no duplicate-poller warnings, and clean single-path task flow in production.

## 7. Lessons Learned

- Never reuse the same Telegram bot token across environments (PROD/LAB/local).
- Treat Telegram poller as a singleton runtime responsibility.
- Keep explicit startup diagnostics/warnings for poller identity, token source, and runtime origin.
- Incident response must include runtime-level consumer inventory, not only code review.

## 8. Preventive Measures

- Enforce strict token isolation per environment (distinct PROD, LAB, local bot tokens).
- Add alerting on `getUpdates conflict (409)` and duplicate-poller warning patterns.
- Keep one canonical poller service enabled; disable polling explicitly elsewhere.
- Add/maintain a poller uniqueness health signal (startup/runtime check) to detect multi-consumer drift quickly.
- Keep automated regression coverage for LAB poller blocking in `backend/tests/test_telegram_poller_lab_guard.py`.

## 9. Preventive Controls Implemented

### 9.1 Automatic duplicate-poller alerting

Implemented in `backend/app/services/telegram_commands.py`:

- New ops alert helper: `_emit_duplicate_poller_ops_alert(reason, token_actual=None)`.
- Uses existing notifier path: `telegram_notifier.send_message(..., chat_destination="ops")`.
- Trigger sources:
  - `reason=advisory_lock_busy` when advisory lock cannot be acquired.
  - `reason=getUpdates_409` when Telegram returns HTTP 409 conflict.
- Alert payload includes:
  - runtime origin
  - hostname/container identity
  - service identity
  - poller flag state
  - token source and masked token suffix only (never full token)
- Rate limiting/dedup:
  - in-memory keyed cooldown via `_POLLER_CONFLICT_ALERT_LAST_TS`
  - configurable by `TELEGRAM_POLLER_ALERT_COOLDOWN_SECONDS` (default `600`, minimum `60`).
- Post-incident cleanup:
  - temporary investigation-only trace logs were removed; only operational `[TG]` startup/poller/error/alert logs remain.

### 9.2 LAB poller hard guard (fail-safe)

Implemented in `process_telegram_commands()`:

- Polling still requires `RUN_TELEGRAM_POLLER=true` (existing behavior).
- New LAB guard blocks polling when runtime is LAB unless an explicit override is present:
  - `ALLOW_LAB_TELEGRAM_POLLER=true`
- LAB detection checks runtime metadata:
  - `RUNTIME_ORIGIN`, `ENVIRONMENT`, `APP_ENV`, `SERVICE_ROLE`, `SERVICE_NAME`, `COMPOSE_PROJECT_NAME`.
- Guard behavior:
  - default: block and log `[TG][GUARD] Poller blocked in LAB runtime ...`
  - explicit override: log `[TG][GUARD] LAB poller override active ...` and continue.

Compose defaults updated:

- `docker-compose.openclaw.yml`: `ALLOW_LAB_TELEGRAM_POLLER=false`
- `docker-compose.yml` (backend local profile): `ALLOW_LAB_TELEGRAM_POLLER=${ALLOW_LAB_TELEGRAM_POLLER:-false}`

## 10. Poller Architecture (Final)

- **Allowed poller:** `backend-aws` in PROD (`RUN_TELEGRAM_POLLER=true`, `RUNTIME_ORIGIN=AWS`).
- **Disallowed by default:** LAB, local, canary, and auxiliary services.
- **Command polling singleton:** enforced by PostgreSQL advisory lock + runtime guardrails.
- **Alert sending path:** may still operate separately from polling where configured (ops/trading notifications), but does not imply poller enablement.

## 11. Verification Playbook

### 11.1 Confirm PROD still polls

1. Verify config:
   - `docker compose --profile aws exec backend-aws printenv | grep -E 'RUN_TELEGRAM_POLLER|RUNTIME_ORIGIN|ALLOW_LAB_TELEGRAM_POLLER'`
2. Verify startup/runtime logs:
   - `docker compose --profile aws logs backend-aws --tail=300 | grep -E '\[TG\]\[POLLER_STARTUP\]|Poller lock acquired|process_telegram_commands called'`
3. Functional check:
   - send `/task <description>` and complete callback flow once; confirm one task path and no duplicates.

### 11.2 Confirm LAB cannot poll

1. In LAB runtime, keep:
   - `RUN_TELEGRAM_POLLER=true` (even if accidentally true)
   - `ALLOW_LAB_TELEGRAM_POLLER` unset/false
2. Verify logs show guard block:
   - `grep -E '\[TG\]\[GUARD\] Poller blocked in LAB runtime'`
3. Verify no polling activity lines:
   - absence of `getUpdates` polling loop logs from LAB runtime.

### 11.3 Safe conflict-alert verification

Use a controlled test runtime with duplicate consumer simulation and check for:

- log: `duplicate_telegram_poller_suspected ...`
- ops alert message sent to ops channel with `reason` and operator metadata
- cooldown behavior: repeated conflicts within cooldown should not flood ops alerts.

## 12. If 409 Reappears

1. Treat as active multi-consumer incident.
2. Run:
   - `backend/scripts/diag/detect_telegram_consumers.sh`
3. Identify and stop non-authorized consumer(s) (LAB/local/external webhook/poller).
4. Verify only PROD poller remains (`backend-aws`).
5. If compromise suspected, rotate ATP Control bot token and update SSM/runtime secrets.
6. Re-run validation checks in Section 11.

## 13. Token Isolation Rules (Mandatory)

- Use distinct tokens for PROD, LAB, and local.
- Never reuse ATP Control PROD token outside PROD poller runtime.
- LAB/OpenClaw config must keep ATP Control token fields empty or isolated from production token.
- Token diagnostics/logging must only expose source names and masked suffixes.
- PROD token rotation/update paths must update both `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ATP_CONTROL_BOT_TOKEN` together in `secrets/runtime.env`.
