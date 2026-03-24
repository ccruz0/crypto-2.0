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
