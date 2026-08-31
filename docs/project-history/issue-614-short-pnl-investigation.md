# Issue #614 — Short P&L reporting bias & SL −$99/−$100 investigation

Date: 2026-08-31  
Ticket: https://github.com/ccruz0/crypto-2.0/issues/614  
Related: #536 (reporting), #566 (SL % tracing), #329 (no live TP amend)

---

## Part 1 — Sales report omitted BUY short closes

### Symptom

The Bali **Reporte de Ventas** (`DailySummaryService.send_sell_orders_report`, scheduled ~07:00 Bali via `scheduler.py`) only queried:

```python
ExchangeOrder.side == SELL AND status == FILLED
```

For shorts:

| Leg | Side | In report before fix? | P&L |
|-----|------|----------------------|-----|
| Open short | SELL | Yes | No (correct) |
| Close short (TP/SL) | BUY | **No** | **Missing** |

Telegram **ORDER EXECUTED** alerts (`telegram_notifier.send_executed_order`) already compute short P&L for BUY covers (`(entry_price - price) * quantity`). The daily sales report did not reuse that path.

### Root cause

Reporting query bias: short realized P&L lives on **BUY** protection legs, not on the opening SELL.

### Fix (this PR)

- Reuse canonical `_short_close_buy_filter()` from `order_position_service.py` (same predicate as position counting).
- Merge deduped SELL rows + BUY short-close rows into one timeline.
- P&L for BUY covers: `(short_entry_price - cover_price) * executed_qty`, parent must be the linked **SELL** entry with qty within 5% tolerance (same anti-guess rules as long closes).

### Live-order path status

**Not on live-order path.** `daily_summary.py` is read-only reporting + Telegram send. No place/cancel/amend TP/SL.

---

## Part 2 — SL short losses ≈ −$99 / −$100

### Observed (Aug 2026 sample, Telegram ATP Control)

- Many short TPs: small % gains (+$0.05–$4) on ~$100-scale notionals.
- Tail SL cluster: ALGO ≈ −$99.50, BTC ≈ −$100.08.
- Win rate ~75% on shorts but aggregate P&L negative (many small wins, few large SL tails).

### Code paths (verified)

| Component | Role |
|-----------|------|
| `system_core_trade_guards.py` | `SYSTEM_CORE_MAX_TRADE_USD` default **$1000** caps entry notional |
| `order_sizing.clamp_order_usd_to_limit` | Caps watchlist `trade_amount_usd` to max-usd-per-order (does not refuse) |
| Watchlist `sl_percentage` | Configured **3%** on symbols (29/29 in prod audit cited by #566) |
| `tp_sl_order_creator.ensure_spot_oco_protection` | Normal OCO path reads watchlist `sl_percentage` |
| `sl_trigger_guard._DEFAULT_SL_PCT = 10.0` | Used when `sl_percentage` is **None/≤0** during **trigger repair** (`ensure_valid_sl_trigger`) |
| `sl_trigger_guard.compute_market_relative_sl` | Recalculates SL from **market ref**, not entry, when trigger is stale/invalid |
| #566 logging | `[SL_PCT_SOURCE]` / `[SL_PCT_DEFAULT]` traces which path was taken (observability only) |

Short SL P&L formula (same as `trade_outcome_builder.compute_pnl` for SELL entry):

```
pnl_usd = (entry_price - exit_price) * quantity   # loss when exit > entry
pnl_pct ≈ (exit - entry) / entry * 100
```

### Arithmetic check

| Notional | SL % | Expected loss |
|----------|------|---------------|
| ~$100 | 3% | ~$3 |
| ~$100 | 10% | ~$10 |
| ~$1000 | 3% | ~$30 |
| **~$1000** | **10%** | **~$100** |

ALGO −$99.50 and BTC −$100.08 match **~$1000 notional × ~10% adverse move**, not 3% on ~$100.

The Aug sample’s small TP wins (+$0.05–$4) align with ~$100-sized positions and ~1–3% TP. The −$99/−$100 tail aligns with max-size (~$1000) shorts stopped at ~10%.

### Verdict

**Not a reporting or P&L calculation bug.** The magnitudes are consistent with:

1. **Position sizing policy** — entries capped toward `SYSTEM_CORE_MAX_TRADE_USD` / `maxUsdPerOrder` (~$1000).
2. **SL percentage fallback** — when the trigger guard repairs without a configured `sl_percentage`, house default **10%** applies (#566 mechanism). Prod evidence: 24/28 deep stops on SELL entries averaged −9.17% with stop placed ~+10% from entry vs configured +3%.

### Why no code change in this PR for part 2

Changing `_DEFAULT_SL_PCT`, watchlist lookup, or OCO/SL creation would touch **live order placement paths** (`tp_sl_order_creator.py`, `sl_trigger_guard.py`, `exchange_sync.py`). That requires Carlos/JARVIS CEO approval (#329 guardrails).

Recommended follow-up (separate ticket, human-gated):

- Correlate `[SL_PCT_SOURCE]` / `[SL_PCT_DEFAULT]` logs for ALGO/BTC Aug SL fills.
- If logs confirm NULL/missed watchlist on repair path, fix **lookup only** with targeted tests — not a blind default change.

---

## Verification

```bash
cd backend && python -m pytest tests/test_daily_summary_sales_pnl.py tests/test_daily_summary_sales_dedupe.py -q
```

Manual: after deploy, compare next Bali sales report totals against Telegram ORDER EXECUTED short SL/TP covers for the same 24h window.
