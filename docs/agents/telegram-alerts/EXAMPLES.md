# Telegram and Alerts Agent — Examples

**Version:** 1.0  
**Date:** 2026-03-15

---

## Issue-to-Agent Mappings

| Notion Task Title / Details | Type | Route Reason | Agent |
|----------------------------|------|--------------|-------|
| "Alerts not being sent" | telegram | task_type:telegram | telegram_alerts |
| "Duplicate alerts on every signal" | bug | keyword:alert | telegram_alerts |
| "Telegram throttle too aggressive" | - | keyword:throttle | telegram_alerts |
| "Kill switch blocking all notifications" | - | keyword:kill switch | telegram_alerts |
| "Repeated alerts for same trade" | - | keyword:repeated alerts | telegram_alerts |
| "Missing alerts after deploy" | - | keyword:missing alerts | telegram_alerts |
| "Approval noise - too many pings" | - | keyword:approval noise | telegram_alerts |
| "TELEGRAM_CHAT_ID wrong channel" | - | keyword:chat_id | telegram_alerts |

---

## Example Output (Minimal Valid)

```markdown
## Issue Summary
Alerts stopped after deploy. RUN_TELEGRAM is true but no messages reach the configured chat.

## Scope Reviewed
- backend/app/services/telegram_notifier.py
- backend/app/services/alert_emitter.py
- docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md

## Confirmed Facts
- RUN_TELEGRAM=true in runtime.env
- TELEGRAM_CHAT_ID is set (value not logged)
- telegram_notifier.send_alert() is called from alert_emitter
- No exceptions in logs during send

## Mismatches
- Runbook says "check TELEGRAM_BOT_TOKEN" but code uses TELEGRAM_CHAT_ID for channel
- alert_emitter checks ENVIRONMENT=="production" before sending; LAB may have ENVIRONMENT=staging

## Root Cause
ENVIRONMENT env var is "staging" on LAB. alert_emitter skips send when ENVIRONMENT != "production".

## Proposed Minimal Fix
1. Verify ENVIRONMENT in runtime.env on LAB.
2. If alerts should go to LAB: add LAB to allowed environments in alert_emitter, or set ENVIRONMENT=production for alert testing.
3. Update runbook to document ENVIRONMENT requirement.

## Risk Level
LOW — config change only; no code change to send logic.

## Validation Plan
1. Set ENVIRONMENT=production (or add LAB to allowlist).
2. Trigger a test alert.
3. Confirm message in Telegram.
4. Revert if unintended side effects.

## Cursor Patch Prompt
Read docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md and add a bullet: "ENVIRONMENT must be 'production' (or allowlist) for alerts to send. LAB defaults to staging."
```

---

## Validation Checklist (Human Review)

- [ ] Scope Reviewed cites telegram_notifier, alert_emitter, or signal_throttle
- [ ] Confirmed Facts references real code/config (no invented env vars)
- [ ] No tokens or secrets in output
- [ ] Proposed Minimal Fix is actionable (file paths, exact steps)
- [ ] Cursor Patch Prompt is safe (no credential changes)
- [ ] Risk Level justified
