# CRO_USD Signal Decisions & Throttle Behavior

Source logs collected from the AWS backend on **2025‑11‑27** using:

```
docker compose logs backend --tail 2000 | grep -i "CRO_USD"
```

All timestamps refer to UTC. At this time the strategy profile resolved to **Swing / Aggressive** with `minPriceChangePct = 1%` and `alertCooldownMinutes = 5`.

| Timestamp (UTC) | Side | Price (USD) | RSI | Decision | Notes |
| --- | --- | --- | --- | --- | --- |
| 13:52:15 | BUY | 0.1124 | 55.3 | REJECT (no signal) | `calculate_trading_signals` returned `buy_signal=False` because RSI remained well above the configured buy threshold (≤40). Throttle state was not updated. |
| 13:52:15 | SELL | 0.1124 | 55.3 | REJECT (no signal) | RSI below the SELL trigger (≥70) and no MA reversal → `sell_signal=False`. |
| 13:54:11 | BUY | 0.1125 | 57.5 | REJECT (no signal) | Indicators still outside BUY criteria, so no candidate emitted; throttling was not evaluated. |
| 13:54:11 | SELL | 0.1125 | 57.5 | REJECT (no signal) | Price above MA50/EMA10 but RSI < 70 → SELL path skipped. |
| 13:58:03 | BUY | 0.1127 | 60.2 | REJECT (no signal) | Even though price drifted +0.3% since the last evaluation, the signal block never emitted a BUY candidate because momentum indicators stayed neutral. |
| 13:58:03 | SELL | 0.1127 | 60.2 | REJECT (no signal) | SELL candidate still false for the same indicator reasons. |
| 13:58:34 | BUY | 0.1127 | 60.2 | REJECT (no signal) | Latest cycle – unchanged outcome. |
| 13:58:34 | SELL | 0.1127 | 60.2 | REJECT (no signal) | Latest cycle – unchanged outcome. |

## Observations

- The monitor consistently refreshed `CRO_USD` from the DB, logged `_log_symbol_context` for both BUY and SELL, and exited early because **no signal candidate** satisfied the RSI/MA rules.  
- Since no candidate was emitted, neither throttling (`should_emit_signal`) nor alert delivery (`should_send_alert`) advanced to the ACCEPT state.  
- There are **no consecutive ACCEPT logs** in the inspected window. Every cycle remained in WAIT, so price/time throttles were never required.  
- The per-symbol logs confirm that strategy thresholds (`minPriceChangePct = 1%`, cooldown 5 minutes) were respected—the system simply never produced a candidate that could challenge those guards.

If future logs ever show a BUY/SELL candidate for `CRO_USD`, re-run the same command and extend this table with the new price/Δprice/Δtime/decision rows to keep a historical audit trail.


