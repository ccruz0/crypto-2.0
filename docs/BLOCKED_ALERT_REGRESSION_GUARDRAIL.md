# Blocked Alert Regression Guardrail

**Date:** 2025-12-01  
**Status:** ✅ Active

---

## Purpose

This document defines a **HARD FAILURE CONDITION** for all Watchlist and alert-related audits. Any presence of legacy alert blocking patterns must cause audits to immediately fail.

---

## The Rule

**Portfolio / business rules may block ORDERS, but must NEVER block ALERTS.**

If ANY of the following patterns are found in Monitoring entries or backend logs, the audit MUST immediately FAIL:

### Patterns to Search For

1. **Exact strings:**
   - `'send_buy_signal verification'`
   - `'send_sell_signal verification'`
   - `'Alerta bloqueada por send_buy_signal verification'`
   - `'Alerta bloqueada por send_sell_signal verification'`

2. **Combined patterns:**
   - `'BLOQUEADO'` (or `'BLOCKED'`) together with `'send_buy_signal'`
   - `'BLOQUEADO'` (or `'BLOCKED'`) together with `'send_sell_signal'`

### Where to Check

1. **Backend logs:**
   ```bash
   grep -E "(send_buy_signal verification|send_sell_signal verification|BLOQUEADO.*send_buy|BLOQUEADO.*send_sell|BLOCKED.*send_buy|BLOCKED.*send_sell)" backend/logs/*.log
   ```

2. **Monitoring → Telegram Messages:**
   - Check `/api/monitoring/telegram-messages` endpoint
   - Check the Monitoring tab in the dashboard
   - Look for any messages containing the patterns above

3. **Docker logs (AWS):**
   ```bash
   docker logs automated-trading-platform-backend-1 2>&1 | grep -E "(send_buy_signal verification|send_sell_signal verification|BLOQUEADO.*send_buy|BLOQUEADO.*send_sell)"
   ```

---

## Action on Detection

If any of these patterns are detected:

1. **Mark the audit as FAILED**
   - Do NOT claim success
   - Do NOT proceed with normal validation

2. **Add a section "Blocked Alert Regression Detected" to the report**
   - List all offending messages found
   - Include timestamps and symbol names
   - Include file paths and line numbers if available

3. **Start a fix loop:**
   - Check `backend/app/services/telegram_notifier.py`
   - Check `backend/app/services/signal_monitor.py`
   - Remove any logic that blocks alerts after conditions are met
   - Ensure alerts are always sent when:
     - `decision=BUY` (or `decision=SELL`)
     - `alert_enabled=true`
     - `buy_alert_enabled=true` (or `sell_alert_enabled=true`)
     - Throttle allows

4. **Redeploy and re-validate:**
   - Deploy fixes to AWS
   - Wait for monitor cycles
   - Re-check logs for the patterns
   - Continue until NO patterns are found

---

## Rationale

Alerts serve as notifications to users about trading opportunities. They must **always** be sent when business rules are satisfied, regardless of:
- Portfolio risk limits (risk blocks orders, not alerts)
- Internal verification checks (verification should happen before calling send functions)
- Any other business logic (except throttle rules)

The presence of "send_buy_signal verification" blocking messages indicates that:
- Redundant verification is happening in `telegram_notifier.py`
- Or blocking logic exists in `signal_monitor.py` that treats verification failures as blocks
- This violates the core principle that alerts must never be blocked after conditions are met

---

## Historical Context

This guardrail was added after fixing a critical bug where:
- `telegram_notifier.send_buy_signal()` was performing redundant verification
- `SignalMonitorService` was treating `False` returns as blocks
- Alerts were being blocked with "Alerta bloqueada por send_buy_signal verification"

The fix removed:
- Redundant verification in `telegram_notifier.py`
- Blocking logic in `signal_monitor.py` that treated `False` as a block

This guardrail ensures these patterns never return.

---

## Integration with Workflows

All Watchlist and alert-related workflows now include this HARD FAILURE CONDITION:

- **Strict Watchlist Audit**
- **Strict Watchlist Runtime Audit**
- **SignalMonitor Deep Audit**

See:
- `docs/WORKFLOW_STRICT_WATCHLIST_AUDIT.md`
- `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- `.cursor/workflows.json`

---

## Testing

To verify this guardrail is working:

1. Run any Watchlist/alert audit workflow
2. The workflow should check for these patterns
3. If patterns are found, the audit should fail immediately
4. The report should include a "Blocked Alert Regression Detected" section

---

## Related Files

- `backend/app/services/telegram_notifier.py` - Should NOT block alerts
- `backend/app/services/signal_monitor.py` - Should NOT block alerts
- `docs/ALERT_DELIVERY_DEBUG_REPORT.md` - Historical fix documentation

---

## Maintenance

This guardrail should be:
- Checked during every Watchlist/alert audit
- Updated if new blocking patterns are discovered
- Referenced in all new alert-related workflows

**Last Updated:** 2025-12-01

