# BTC FIFO ghost lots — safe plan (Expected TP)

**Date:** 2026-09-02  
**Context:** Live BTC short ~−0.0013 BTC (~$103) with OCO on book; Expected TP also
lists ~11 historical «Compra» FIFO parents (Nov 2025–May 2026) with large negative
PnL (~−$1.6k aggregate). Those rows are **ledger ghosts**, not 11 live shorts.  
**Related:** [#617](https://github.com/ccruz0/crypto-2.0/issues/617),
[#603](https://github.com/ccruz0/crypto-2.0/pull/603) (books-only stub close pattern).

---

## 1. Classify: live short vs FIFO ghosts

| Class | What it is | How to recognize | Action |
|-------|------------|------------------|--------|
| **Live short** | Real exchange position + OCO | Wallet ≈ −0.0013 BTC; ACTIVE SL+TP on book (~41531/41530); one protected SELL entry parent | **Never** place/cancel/amend those legs |
| **FIFO ghost parents** | Open lots in `rebuild_open_lots` without wallet capacity | `exceeds_wallet=true` after align; often old BUY rows on a short wallet; aggregate PnL looks like −10%…−19% each | Display filter and/or books-only close (see below) |
| **Dust residue** | Sub-$5 notional leftover | Below `NAKED_SHORT_MIN_POSITION_USD` / Portfolio **Limpiar dust** | Market flatten via Portfolio only if operator chooses |

**Wallet truth:** `|wallet|` is authoritative. Phantom lots stay tagged with
`exceeds_wallet` and are excluded from coverage/qty aggregates (see
`test_expected_tp_phantom_lot_aggregates.py`).

**Audit truth (#617):** Hourly SL/TP audit skips naked FIFO parent scan when
`_wallet_sum_covers_sl_tp(has_sl, has_tp)` — informational ghosts must not drive
alerts or invent-heal.

---

## 2. Safe dust (<$5)

- **Portfolio tab → Limpiar dust** for sub-$5 unprotected lots (`portfolioLotActions.ts`,
  floor = $5, matches SL/TP checker).
- **Do not** use invent-heal or background heal for dust.
- **Do not** auto-flatten; operator confirms market close.

---

## 3. Hide / clear ghosts without invent-heal ON

### A. Display-only (gated, default OFF)

Env: `EXPECTED_TP_HIDE_WALLET_COVERED_PHANTOMS=false` (default).

When **true** AND wallet-sum SL+TP covers the symbol:

- Expected TP **details** omit `exceeds_wallet` rows from `entry_orders` / `matched_lots`.
- Response adds `wallet_covered_phantoms_hidden` count + banner in UI.
- **No DB writes, no exchange calls, no invent-heal.**

### B. Books-only close (manual ops, #603 pattern)

For **bot-origin** stuck parents (APT precedent):

- Workflow: `Ops — cerrar ghost lots en libros` (`close_ghost_lots_2026_08_30.py`).
- **Dry-run default**; `--live` inserts paired `STUB-CLOSED-*` rows only.
- Guards: `require_bot_origin`, `exchange_create_time` age ≥14d, no FILLED children.

**BTC manual import parent `5755600480707749502` is explicitly OUT OF SCOPE**
(no `trade_signal_id` / `order_intent` — would contaminate history). Do not stub-close.

### C. Explicitly forbidden without human gate

- `ensure_spot_oco_protection` / full wallet invent-heal (#329)
- Place/cancel/amend live SL/TP on the live short OCO
- Broad FIFO reconciliation scripts without per-row guards

---

## 4. Verification steps (prod / post-deploy)

1. **Live short untouched:** Confirm OCO order ids ~41531/41530 remain ACTIVE on exchange.
2. **Wallet:** BTC balance still ≈ −0.0013; net Expected TP qty matches `|wallet|`.
3. **Flag OFF (default):** Details still list ghost rows with `exceeds_wallet`; aggregates unchanged.
4. **Flag ON (operator):** Set `EXPECTED_TP_HIDE_WALLET_COVERED_PHANTOMS=true`, restart backend;
   details show live short only + banner with hidden count; summary aggregates unchanged.
5. **Audit (#617):** Hourly SL/TP digest has no naked_parent rows for BTC when wallet-sum covered.
6. **Tests:** `pytest backend/tests/test_expected_tp_hide_wallet_covered_phantoms.py`
   and `test_naked_parent_wallet_sum_issue_617.py`.

---

## 5. Rollback

| Change | Rollback |
|--------|----------|
| Display filter flag ON | Set `EXPECTED_TP_HIDE_WALLET_COVERED_PHANTOMS=false` (or unset) + backend restart |
| Code deploy | Revert PR; redeploy prior backend/frontend image |
| Books-only stubs (#603) | **Do not delete** stubs without forensic review; they are intentional ledger closes |

---

## 6. Operator checklist (BTC today)

1. Treat **one** live short + OCO as real exposure (~$103).
2. Treat **11 Compra** FIFO rows as ledger noise until books-only close is approved per row.
3. Keep invent-heal **OFF**.
4. Optional: enable display filter after deploy to reduce dashboard noise.
5. For future bot ghosts: use #603 workflow dry-run first, never on manual imports.
