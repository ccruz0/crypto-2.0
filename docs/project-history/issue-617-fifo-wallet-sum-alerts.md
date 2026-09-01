# Issue #617 — FIFO parents hidden by wallet-sum (2026-09-01)

## Symptom

HOURLY SL/TP AUDIT listed four `naked_parent` rows whose qty was already
explained by live wallet-level SL/TP:

| Symbol   | Parent id              | Notes                                      |
|----------|------------------------|--------------------------------------------|
| APT_USD  | 5755600492526823562    | Aug-2025 ghost short; live APT has SL+TP   |
| APT_USD  | 5755600492576389211    | Same                                       |
| BTC_USD  | 5755600480707749502    | Old FIFO row; wallet covered               |
| BONK_USD | 5755600493224387170    | Leftover OCO TP without SL (known; no heal)|

Live APT (Sep-2026) uses parents `73817490102143640` / `73817490102143639`.

## Fix (read-only audit)

When `_wallet_sum_covers_sl_tp(has_sl, has_tp)` is true for a wallet row,
`check_positions_for_sl_tp` no longer scans or reports naked FIFO entry
parents. `_iter_naked_entry_parents` is unchanged for other callers.

## Out of scope

- Invent-heal / `ensure_spot_oco_protection` — stays OFF (#329)
- Placing or amending BONK SL for parent `…7170`
- DB reconciliation of orphan FIFO rows (no safe no-exchange write identified)

## BONK follow-up

Parent `5755600493224387170` may still appear when wallet-sum lacks SL
(`has_sl=false`). Document only; do not recreate SL on exchange in #617.

## Verify

- `pytest backend/tests/test_naked_parent_wallet_sum_issue_617.py`
- Hourly audit with fully covered APT/BTC wallets → zero naked_parent rows
