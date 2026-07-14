# Open orders reduction + guardrail verification (2026-07-14)

## Context

Production had **34 pending TAKE_PROFIT orders** vs `MAX_OPEN_ORDERS_TOTAL=10`.
Goal: block new entry orders, reduce count via safe orphan cleanup, ensure count drops as TP/SL fill.

## Part 1 — Blocking verification

| Path | Guard | Status |
|------|-------|--------|
| Orchestrator BUY/SELL | `_orchestrator_order_guard` → `can_place_real_order()` | OK (PR #175, merged) |
| Legacy BUY | `can_place_real_order()` before `place_market_order` | OK |
| Legacy SELL | **Missing** `can_place_real_order()` | **Fixed** (this session) |
| Manual API (`routes_orders.py`) | `can_place_real_order()` for MARKET/LIMIT | OK |
| Protective SL/TP creation | Bypasses MAX_OPEN_ORDERS (by design) | OK |

Verified live: `can_place_real_order('ETH_USDT', BUY/SELL)` → `blocked: MAX_OPEN_ORDERS_TOTAL (34/10)`.

## Part 2 — Inventory & orphan cleanup (production, user-approved)

### Before
- **34** pending TP orders (count source: `count_total_open_positions`)
- By symbol: BTC_USD 13, ETH_USDT 9, DOGE_USD 5, DOT_USD 3, ETH_USD 3, SOL_USD 1

### Safe cancel criteria
TP is safe to cancel when **parent entry lot is closed** (parent not in FIFO `open_lots`) and order is absent from exchange open orders.

### Cancelled (6 orders → count 34 → 28)

| Symbol | Order ID | Qty | Reason |
|--------|----------|-----|--------|
| BTC_USD | 5755600489253467765 | 0.29925 | Parent filled, not in open lots |
| BTC_USD | 73817490101969014 | 0.14102 | Parent filled, not in open lots |
| BTC_USD | 73817490101969016 | 0.00934 | Parent filled, not in open lots |
| BTC_USD | 73817490101969017 | 0.00872 | Parent filled, not in open lots |
| BTC_USD | 73817490101969015 | 0.02512 | Ghost TP (ACTIVE in DB, not on exchange, no parent) |
| DOT_USD | 73817490101973977 | 11.99 | Parent filled, not in open lots |

### Kept (28 TPs — protecting live FIFO lots / shorts)
All remaining TPs have `parent_order_id` present in current `open_lots` for their symbol.
Not cancelled: DOGE_USD (5), ETH_USDT (9), ETH_USD (3), SOL_USD (1), BTC_USD (8), DOT_USD (2).

### After
- **28/10** pending TP orders
- New MARKET entries remain blocked until count < 10

## Part 3 — How count decreases naturally

1. When a TP (or SL) **fills** on Crypto.com, `exchange_sync` resolves status via order history and marks `ExchangeOrder.status = FILLED`.
2. `count_total_open_positions()` only counts TP orders in NEW/ACTIVE/PARTIALLY_FILLED → count drops automatically.
3. Protective SL/TP creation is **not** blocked by the limit (existing positions stay protected).

## Code change (small PR)

- Add `can_place_real_order()` to legacy `_create_sell_order_impl` (parity with legacy BUY).
- Test: `backend/tests/test_legacy_sell_guardrails.py`

## Rollback

- Orphan cleanup: cannot undo filled/cancelled exchange orders; cancelled orphans were stale (no open lot).
- Code: revert PR; redeploy backend.
