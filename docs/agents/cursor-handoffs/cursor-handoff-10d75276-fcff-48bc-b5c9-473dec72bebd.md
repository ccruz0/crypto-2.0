## Task

RESET: purchase_price becomes null/missing  (Notion: `10d75276-fcff-48bc-b5c9-473dec72bebd`)

## Repo

watchlist.py, watchlist_master.py, routes_dashboard.py, sl_tp_checker.py, signal_monitor.py, signal_evaluator.py, routes_market.py, routes_signals.py

## Root cause

purchase_price can become null via multiple paths: (1) Payload-driven null in routes_dashboard.py PATCH handler when frontend sends purchase_price: null; (2) Never populated when no BUY order or sync writes it; (3) Sync gap between order fill and watchlist update.

## Affected files

- `backend/app/models/watchlist.py`
- `backend/app/models/watchlist_master.py`
- `backend/app/api/routes_dashboard.py`
- `backend/app/services/sl_tp_checker.py`
- `backend/app/services/signal_monitor.py`
- `backend/app/services/signal_evaluator.py`
- `backend/app/api/routes_market.py`
- `backend/app/api/routes_signals.py`

## Constraints

- Build on the current implementation
- Change only the parts needed
- Keep the rest untouched
- Do not refactor unrelated code
- Preserve existing architecture unless explicitly required

## Expected outcome

Guard PATCH to not allow purchase_price=null when item has filled BUY; ensure order-fill sync updates purchase_price from avg_price; frontend avoid sending null unless explicit.

## Testing requirements

PATCH with null before/after fix; simulate order fill; run signal evaluation with null purchase_price.
