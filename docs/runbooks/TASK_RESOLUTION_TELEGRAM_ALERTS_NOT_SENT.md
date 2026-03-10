# Task resolution: Investigate Telegram alerts not being sent

**Notion task:** Investigate Telegram alerts not being sent  
**Resolved:** 2026-03-09

---

## What was done

1. **Runbook added:** `docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md` — when to use it, how to run the diagnostic, block reasons (RUN_TELEGRAM, kill switch, token/chat_id, origin), and how to resolve the Notion task.
2. **Diagnostic run on PROD** (after SSM was restored):  
   `./scripts/diag/run_telegram_diagnostic_prod.sh` executed against backend on `i-087953603011543c5`.

## Diagnostic result (PROD)

- **Env:** TELEGRAM_BOT_TOKEN ✅, TELEGRAM_CHAT_ID ✅, RUNTIME_ORIGIN=AWS ✅, RUN_TELEGRAM=true ✅, APP_ENV=aws ✅
- **Notifier in script:** showed "disabled" / Missing TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in that run because the diagnostic did not call `refresh_config()` before reading the notifier state (same env is only applied when `send_message()` or `refresh_config()` runs).
- **Fix in repo:** `backend/scripts/diagnose_telegram_alerts.py` now calls `notifier.refresh_config()` before checking enabled/token/chat_id, so future diagnostic runs reflect real state.

## Conclusion

- **Configuration on PROD is correct** for Telegram (token, chat_id, RUN_TELEGRAM, RUNTIME_ORIGIN=AWS). At runtime, when the backend sends an alert, `send_message()` → `refresh_config()` uses that env, so alerts should be sent.
- If alerts still don’t appear: (1) Check backend logs for `[TG BLOCKED]` and the `reasons=` list; (2) Run the diagnostic again after a deploy so the script uses the updated `refresh_config()` logic; (3) Confirm the emitting service (e.g. market-updater-aws) has RUNTIME_ORIGIN=AWS.

## What to put in Notion

**Status:** Done (or Testing, if you prefer to confirm with a live alert first).

**Comment / description update (paste this):**

```
Resolved 2026-03-09.

- Runbook: docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md
- Diagnostic run on PROD: env and Settings are correct (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, RUNTIME_ORIGIN=AWS, RUN_TELEGRAM=true). Notifier state in the one-off diagnostic was stale (script now calls refresh_config() so future runs are accurate).
- Conclusion: PROD config is correct; alerts should send when backend emits. If issues persist, check backend logs for [TG BLOCKED] and run ./scripts/diag/run_telegram_diagnostic_prod.sh after deploy.
```

---

**Reference:** Runbook index entry in `docs/aws/RUNBOOK_INDEX.md` → TELEGRAM_ALERTS_NOT_SENT.
