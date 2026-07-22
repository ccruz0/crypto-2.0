# Alert quality scorecard (Phase 1 offline)

**Generated:** 2026-07-22T07:03:19.373403+00:00
**Source:** demo+fixture
**Delta (M1):** 0.005
**Alerts labeled:** 2 / input 2 (skipped 0, errors 0)

Metrics: M1 trend hit · M2 direction · M3 MFE/MAE · M4 TP before SL · M5 expectancy proxy · M7 composite. M6 (alert→fill) not computed here.

## Global

- Mean composite (M7): 0.855
- BUY mean composite: 0.855
- SELL mean composite: 0.855

## Segments (symbol × strategy × side)

| Symbol | Strategy | Side | n | dir@1h | trend@4h | TP<SL | med MFE | med MAE | composite | expectancy |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_USDT | swing-conservative | BUY | 1* | 100.0% | 100.0% | 100.0% | 3.56% | 0.10% | 0.855 | 3.56% |
| ETH_USDT | swing-aggressive | SELL | 1* | 100.0% | 100.0% | 100.0% | 3.44% | 0.10% | 0.855 | 3.44% |

\* n < 20 — segment not rankable per Phase 1 design.

## Sample labeled alerts (first 25)

| id | symbol | side | entry | dir@1h | trend@4h | MFE | MAE | TP<SL | M7 |
|---|---|---|---:|---|---|---:|---:|---|---:|
| 1 | BTC_USDT | BUY | 65000.0000 | Y | Y | 3.56% | 0.10% | Y | 0.855 |
| 2 | ETH_USDT | SELL | 3200.0000 | Y | Y | 3.44% | 0.10% | Y | 0.855 |

## Notes

- Offline only; OHLCV re-fetched from public Binance (or fixture).
- No secrets written; no HostSwapHigh / trading_config / Auto UI changes.
- Design: `docs/project-history/alert-quality-eval-phase1-2026-07-22.md`
