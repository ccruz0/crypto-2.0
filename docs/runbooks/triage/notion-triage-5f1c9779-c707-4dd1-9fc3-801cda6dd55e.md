# Notion monitoring triage: Investigate Telegram failure

- **Notion page id**: `5f1c9779-c707-4dd1-9fc3-801cda6dd55e`
- **Priority**: `high`
- **Project**: `Infrastructure`
- **Type**: `monitoring`

## Affected modules (inferred)

- `backend/app/services/telegram_commands.py`
- `backend/app/services/telegram_notifier.py`
- `backend/app/api/routes_monitoring.py`

## Relevant runbooks

- [TELEGRAM_ALERTS_NOT_SENT.md](../TELEGRAM_ALERTS_NOT_SENT.md) — **primary runbook for this fix**

## Incident summary

- **Symptoms:** Telegram alerts/notifications not being sent (trading alerts, health alerts).
- **Impact:** No Telegram delivery; block reasons logged as `[TG BLOCKED]`.
- **Common causes:** `RUN_TELEGRAM` unset, kill switch off (`tg_enabled_aws`), missing token/chat_id, wrong `RUNTIME_ORIGIN`, or `secrets/runtime.env` not readable by backend.

---

## Cursor: run these steps (actionable fix)

When the user asks Cursor to **pick this triage and run the changes needed**, do the following in order:

1. **Run the Telegram diagnostic (from repo root)**  
   This determines why sends are blocked (env, kill switch, token, origin).
   ```bash
   ./scripts/diag/run_telegram_diagnostic_prod.sh
   ```
   If SSM is unavailable, the script will print the command to run on the instance.

2. **Apply fixes per runbook**  
   Use the diagnostic output and [TELEGRAM_ALERTS_NOT_SENT.md](../TELEGRAM_ALERTS_NOT_SENT.md):
   - If **run_telegram_disabled**: set `RUN_TELEGRAM=true` (or `1`) in the env used by backend-aws and market-updater-aws (e.g. `secrets/runtime.env`, `.env.aws`, or docker env).
   - If **kill_switch_disabled**: enable Telegram in dashboard/settings or set DB `trading_settings` key `tg_enabled_aws` to `true`. You can also call the control API (if available): e.g. `POST /api/control/telegram-enabled` with `{"enabled": true}` for AWS, or set in DB.
   - If **token_missing** or **chat_id_missing**: set `TELEGRAM_BOT_TOKEN`/`TELEGRAM_BOT_TOKEN_AWS` and `TELEGRAM_CHAT_ID`/`TELEGRAM_CHAT_ID_AWS` in `secrets/runtime.env` or `.env.aws`; ensure backend can read the file (e.g. `chmod 644 secrets/runtime.env` on host and restart backend).
   - If **aws_using_local_credentials**: remove or avoid `TELEGRAM_*_LOCAL` on PROD; use only `TELEGRAM_*_AWS` or generic vars.
   - If **origin** blocks: ensure backend and market-updater-aws have `RUNTIME_ORIGIN=AWS` (or equivalent) in docker-compose / env.

3. **Restart backend after env/secret changes**  
   On PROD via SSM or on instance:
   ```bash
   cd /home/ubuntu/automated-trading-platform && docker compose --profile aws restart backend-aws
   ```
   If you changed `secrets/runtime.env` permissions or content, use the same host where the stack runs.

4. **Re-run diagnostic and optionally send test message**  
   Run `./scripts/diag/run_telegram_diagnostic_prod.sh` again and follow any “FIXES NEEDED” it prints. If the runbook or diagnostic suggests a test send, do it.

5. **If env is set but notifier still disabled** — Re-run diagnostic to see Block reasons; if `kill_switch_disabled`, enable Telegram (dashboard/settings or DB `tg_enabled_aws = true`) and restart backend.

6. **Update this triage or the Notion task**  
   Add a short note (e.g. “Fixed: RUN_TELEGRAM set in runtime.env; backend restarted”) or update the Notion task status to Testing/Done per [TELEGRAM_ALERTS_NOT_SENT.md § Resolving the Notion task](../TELEGRAM_ALERTS_NOT_SENT.md#6-resolving-the-notion-task).

Do not change trading/order lifecycle logic; limit changes to Telegram config, env, and runbook-recommended fixes.

---

## Nota de ejecución (Cursor triage test)

- **Pasos ejecutados:** (1) Diagnóstico PROD, (2) Habilitado kill switch vía `POST /api/settings/telegram` con `{"enabled": true}` → `tg_enabled_aws = true`, (3) Reinicio de backend en PROD vía SSM, (4) Re-ejecución del diagnóstico.
- **Resultado:** Kill switch AWS = **ENABLED**. En el proceso del script de diagnóstico (exec en el contenedor) el notifier sigue reportando token/chat_id ausentes; env vars y Settings() sí aparecen con valor en las comprobaciones previas. Posible causa: el proceso ejecutado con `docker compose exec` no hereda el mismo env que el worker principal (entrypoint). Siguiente: asegurar que el servicio backend-aws tenga `env_file: secrets/runtime.env` (o equivalent) en compose y que el entrypoint exporte las vars para que cualquier proceso en el contenedor las vea; o revisar por qué `refresh_config()` no ve token en ese contexto.

---

## Segunda ejecución (continuación de tarea)

- **Pasos ejecutados (2026-03-10):** (1) Diagnóstico PROD — env y Settings OK, notifier disabled. (2) Kill switch habilitado de nuevo vía `POST /api/settings/telegram` → `{"ok":true,"enabled":true}`. (3) Reinicio backend-aws en PROD vía SSM; contenedor Up (healthy). (4) Re-ejecución del diagnóstico.
- **Resultado:** Mismo estado: env vars y Settings muestran TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID; el notifier sigue `Enabled: False` (Missing TELEGRAM_BOT_TOKEN / Missing TELEGRAM_CHAT_ID). Los **workers gunicorn** en producción podrían sí tener el token (env_file cargado al arranque); el fallo podría limitarse al proceso del script de diagnóstico (exec). **Siguiente:** Verificar en producción si los envíos reales a Telegram funcionan (p. ej. disparar una alerta de prueba o revisar logs por `[TG BLOCKED]` vs envíos exitosos). Si en producción tampoco se envían, revisar `telegram_notifier.refresh_config()` y cómo lee token en el proceso worker (Settings singleton vs env en el worker).
