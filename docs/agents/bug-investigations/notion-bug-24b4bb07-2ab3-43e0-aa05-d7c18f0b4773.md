# Bug investigation: Fix purchase_price discrepancy across trading system

- **Notion page id**: `24b4bb07-2ab3-43e0-aa05-d7c18f0b4773`
- **Priority**: `High`
- **Project**: `Crypto Trading`
- **Type**: `Bug`
- **GitHub link**: ``

## Inferred area

- **Area**: Orders / Exchange Sync
- **Matched rules**: orders-sync

## Affected modules

- `backend/app/services/exchange_sync.py`
- `backend/app/models/exchange_order.py`
- `backend/app/models/trade_signal.py`
- `backend/app/api/routes_orders.py`

## Relevant docs

- [docs/architecture/system-map.md](../../architecture/system-map.md)
- [docs/agents/context.md](../context.md)
- [docs/agents/task-system.md](../task-system.md)
- [docs/decision-log/README.md](../../decision-log/README.md)
- [docs/openclaw/OPENCLAW_UI_IN_DASHBOARD.md](../../openclaw/OPENCLAW_UI_IN_DASHBOARD.md)

## Relevant runbooks

- [docs/aws/RUNBOOK_ORDER_HISTORY_SYNC_DEBUG.md](../../aws/RUNBOOK_ORDER_HISTORY_SYNC_DEBUG.md)
- [docs/aws/RUNBOOK_ORDER_HISTORY_ISOLATION.md](../../aws/RUNBOOK_ORDER_HISTORY_ISOLATION.md)
- [docs/runbooks/ORDER_HISTORY_DASHBOARD_DEBUG.md](../../runbooks/ORDER_HISTORY_DASHBOARD_DEBUG.md)

## Bug details

- **Reported symptom**: ## Title
Fix purchase_price discrepancy across trading system

---

## 1. Context
There is a discrepancy in the purchase_price logic.

Observed facts:
- watchlist_items and watchlist_master contain purchase_price values or values derivable from executed BUY orders.
- Despite this, some parts of the system behave as if no purchase_price exists.

Available data sources:
- Database tables:
	- watchlist_items
	- watchlist_master
	- exchange_orders / BUY filled orders
- Backend services and API layers
- Logs and runtime behavior

Components involved:
- SL/TP logic
- Signal evaluation
- API serialization
- Trading decision flow

Affected flow:
Data retrieval → price resolution → trading logic → SL/TP → API → UI

---

## 2. Expected Behavior
- The system must correctly detect purchase_price when it exists in any valid source.
- purchase_price must be resolved using a clear precedence across:
	1) watchlist_items
	2) watchlist_master
	3) executed BUY orders
- SL/TP logic must use this value.
- P&L calculations must use this value.
- Trading decisions must not be blocked when purchase_price exists.

---

## 3. Actual Behavior
- The system incorrectly assumes that some coins do not have a purchase_price.
- This occurs even when data exists in DB or is derivable from orders.

Impact:
- SL/TP creation may be blocked
- P&L calculations may be incorrect
- Trading decisions may fail or be skipped

Observed at:
- Service logic level
- API responses
- Downstream trading behavior

---

## 4. Scope / Areas to Review
- backend/app/services/sl_tp_checker.py → entry_price and purchase_price fallback logic
- backend/app/services/signal_evaluator.py → last_buy_price logic
- backend/app/api/routes_dashboard.py → purchase_price serialization
- backend/app/api/routes_signals.py → last_buy_price in signals
- Synchronization between watchlist_items and watchlist_master
- Order-derived price logic from exchange_orders

---

## 5. Investigation Objectives
- Audit all purchase_price sources
- Identify incorrect conditions or missing fallbacks
- Review synchronization between tables
- Detect logic errors in precedence handling
- Identify inconsistencies between:
	- DB
	- service layer
	- API layer

---

## 6. Execution Instructions (OpenClaw)
Follow all phases strictly:
- Phase 1 — Source of truth mapping
- Phase 2 — Code audit
- Phase 3 — Data consistency audit
- Phase 4 — Root cause
- Phase 5 — Fix design
- Phase 6 — Validation

---

## 7. Rules
- Do not propose changes without identifying the root cause
- Prefer minimal fixes
- Do not modify unrelated behavior
- Do not assume data correctness without verification
- Do not skip phases

---

## 8. Success Criteria
- Exact failure point is identified
- Clear precedence for purchase_price is defined
- Minimal safe fix is proposed
- Validation across multiple scenarios is completed
- Output is directly usable in Cursor

---

## 9. Expected Output Format
- Findings
- Root cause
- Recommended fix
- Validation
- Cursor prompt
- **Reproducible**: (to be confirmed)
- **Severity**: (inferred from priority: High)

## Investigation checklist

- [ ] Confirm current behavior (logs, health endpoint, dashboard)
- [ ] Identify root cause in affected module(s)
- [ ] Determine smallest safe fix
- [ ] Verify fix does not affect unrelated areas
- [ ] Update relevant docs/runbooks if behavior changes
- [ ] Validate (tests/lint/manual) before marking deployed

---

- Investigation note touched by agent callback (no overwrite).
