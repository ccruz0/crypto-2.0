# Execution and State Agent — Examples

**Version:** 1.0  
**Date:** 2026-03-15

---

## Issue-to-Agent Mappings

| Notion Task Title / Details | Type | Route Reason | Agent |
|----------------------------|------|--------------|-------|
| "Order not in open orders" | order | task_type:order | execution_state |
| "Order not found in dashboard" | - | keyword:order | execution_state |
| "Exchange vs DB mismatch" | - | keyword:db mismatch | execution_state |
| "Dashboard showing wrong order state" | - | keyword:dashboard mismatch | execution_state |
| "State reconciliation failed" | - | keyword:state reconciliation | execution_state |
| "SL/TP order lifecycle unclear" | - | keyword:sl/tp | execution_state |
| "Missing order - sync says executed" | - | keyword:missing order | execution_state |
| "Order history vs open orders inconsistent" | - | keyword:order history | execution_state |

---

## Example Output (Minimal Valid)

```markdown
## Issue Summary
User reports "order not in open orders" but exchange shows order as EXECUTED. Dashboard shows PENDING.

## Scope Reviewed
- backend/app/services/exchange_sync.py
- backend/app/services/signal_monitor.py
- backend/app/services/brokers/crypto_com_trade.py
- docs/ORDER_LIFECYCLE_GUIDE.md

## Confirmed Facts
- exchange_sync fetches open_orders and order_history from Crypto.com API
- "Order not in open orders" does NOT mean canceled — order may be filled (EXECUTED)
- signal_monitor creates orders and listens for lifecycle events
- Dashboard reads from PostgreSQL exchange_order table

## Mismatches
- Dashboard shows PENDING; exchange API order_history shows EXECUTED
- Lifecycle event (order_filled) may not have been processed before user checked
- DB state lags exchange by sync interval

## Root Cause
Order was filled (EXECUTED) on exchange. Sync had not yet written the lifecycle event to DB. User checked open_orders (excludes filled) and dashboard (stale) before sync completed.

## Proposed Minimal Fix
1. Do NOT assume missing from open_orders = canceled.
2. Check order_history and trade_history on exchange for final state.
3. Add runbook step: "If order not in open_orders, query order_history by order_id to confirm EXECUTED vs CANCELED."
4. Consider dashboard note: "State may lag exchange by up to N seconds."

## Risk Level
LOW — documentation and operational guidance only; no order placement changes.

## Validation Plan
1. Reproduce: place order, wait for fill, check open_orders (empty) and order_history (EXECUTED).
2. Confirm runbook step resolves confusion.
3. No code changes to order placement or sync logic.

## Cursor Patch Prompt
Update docs/ORDER_LIFECYCLE_GUIDE.md: add section "Order not in open orders" explaining that this does NOT mean canceled; user must check order_history/trade_history for EXECUTED/CANCELED. Include code path: exchange_sync.fetch_order_history().
```

---

## Validation Checklist (Human Review)

- [ ] Scope Reviewed cites exchange_sync, signal_monitor, or crypto_com_trade
- [ ] Did not assume "missing from open orders" = canceled without exchange confirmation
- [ ] Proposed fix does not change order placement logic
- [ ] Cursor Patch Prompt is read-only or doc-only
- [ ] Root Cause cites exchange API behavior or code path
