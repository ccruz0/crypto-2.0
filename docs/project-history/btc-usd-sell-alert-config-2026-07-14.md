# BTC_USD sell_alert config change (2026-07-14)

## Context

Investigation 6317e904: BTC_USD had `trade_enabled=False` but `sell_alert_enabled=True`.
A SELL signal alert was sent and the orchestrator attempted a real order (margin short with
`ALLOW_SHORTING=true`), bypassing `trade_enabled`.

## Changes applied (production, user-approved)

| Setting | Before | After | Notes |
|---------|--------|-------|-------|
| `BTC_USD.sell_alert_enabled` | `true` | `false` | Blocks automatic SELL alerts for BTC |
| `BTC_USD.trade_enabled` | `false` | unchanged | Trade already OFF |
| `ALLOW_SHORTING` (env) | `true` | unchanged | Global shorting still enabled for other symbols |

## Rationale

- **Option B chosen** (per-symbol `sell_alert_enabled`) instead of global `ALLOW_SHORTING=false`.
- Keeps shorting available for symbols where the user explicitly wants SELL alerts + margin.
- Combined with code fix: orchestrator now calls `can_place_real_order()` before placement.

## Implications of `ALLOW_SHORTING=true` (unchanged)

- Margin SELL without an open long can open a **short** when `trade_on_margin=true` and
  `trade_enabled=true` on that symbol.
- Disabling `sell_alert_enabled` on BTC_USD prevents alert-driven short entries on BTC only.
- To block shorts globally, set `ALLOW_SHORTING=false` in the backend/market-updater env.

## Verification

```sql
SELECT symbol, trade_enabled, sell_alert_enabled, buy_alert_enabled, alert_enabled
FROM watchlist_items WHERE symbol = 'BTC_USD';
```

Expected: `sell_alert_enabled = false`, `trade_enabled = false`.
