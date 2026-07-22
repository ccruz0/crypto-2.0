# Alert quality scorecard (Phase 1 offline)

**Generated:** 2026-07-22T07:54:47.572118+00:00
**Source:** api:https://dashboard.hilovivo.com
**Delta (M1):** 0.005
**Alerts labeled:** 59 / input 131 (skipped 72, errors 0)

Metrics: M1 trend hit · M2 direction · M3 MFE/MAE · M4 TP before SL · M5 expectancy proxy · M7 composite. M6 (alert→fill) not computed here.

## Global

- Mean composite (M7): 0.211
- BUY mean composite: 0.209
- SELL mean composite: 0.216

## Segments (symbol × strategy × side)

| Symbol | Strategy | Side | n | dir@1h | trend@4h | TP<SL | med MFE | med MAE | composite | expectancy |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| BTC_USD | scalp-conservative | BUY | 2* | 100.0% | 100.0% | — | 1.42% | 0.11% | 0.803 | 1.42% |
| BTC_USD | swing-conservative | BUY | 2* | 100.0% | 100.0% | — | 2.22% | 0.11% | 0.804 | 2.22% |
| DOGE_USD | swing-conservative | BUY | 2* | 0.0% | 0.0% | — | 0.16% | 0.53% | 0.000 | -0.53% |
| DOGE_USD | swing-conservative | SELL | 4* | 100.0% | 0.0% | — | 0.60% | 0.10% | 0.468 | -0.12% |
| DOT_USD | swing-conservative | BUY | 7* | 57.1% | 14.3% | 0.0% | 0.52% | 0.76% | 0.315 | -1.47% |
| DOT_USD | swing-conservative | SELL | 5* | 40.0% | 0.0% | — | 0.76% | 0.73% | 0.188 | -0.35% |
| ETH_USD | swing-conservative | BUY | 12* | 0.0% | 0.0% | — | 0.00% | 2.95% | 0.000 | -2.80% |
| ETH_USDT | swing-conservative | BUY | 21 | 23.8% | 23.8% | 21.4% | 0.00% | 3.15% | 0.200 | -0.39% |
| ETH_USDT | swing-conservative | SELL | 4* | 0.0% | 0.0% | — | 0.00% | 0.66% | 0.000 | -0.70% |

\* n < 20 — segment not rankable per Phase 1 design.

## Sample labeled alerts (first 25)

| id | symbol | side | entry | dir@1h | trend@4h | MFE | MAE | TP<SL | M7 |
|---|---|---|---:|---|---|---:|---:|---|---:|
| None | DOT_USD | BUY | 0.8742 | N | N | 0.00% | 2.20% | — | 0.000 |
| None | DOGE_USD | SELL | 0.0736 | Y | N | 0.45% | 0.22% | — | 0.467 |
| None | DOGE_USD | BUY | 0.0736 | N | N | 0.22% | 0.45% | — | 0.000 |
| None | DOGE_USD | SELL | 0.0737 | Y | N | 0.58% | 0.08% | — | 0.468 |
| None | DOT_USD | BUY | 0.8730 | N | N | 0.00% | 2.29% | — | 0.000 |
| None | DOT_USD | SELL | 0.8525 | N | N | 0.06% | 1.94% | — | 0.000 |
| None | DOT_USD | BUY | 0.8525 | Y | Y | 1.94% | 0.06% | — | 0.804 |
| None | DOT_USD | SELL | 0.8565 | Y | N | 0.53% | 1.46% | — | 0.467 |
| None | DOT_USD | SELL | 0.8577 | Y | N | 3.00% | 0.73% | — | 0.471 |
| None | ETH_USDT | SELL | 1923.1900 | N | N | 0.07% | 0.87% | — | 0.000 |
| None | ETH_USDT | BUY | 1923.1900 | Y | Y | 0.87% | 0.07% | — | 0.802 |
| None | ETH_USDT | SELL | 1919.7500 | N | N | 0.00% | 1.05% | — | 0.000 |
| None | DOT_USD | SELL | 0.8263 | N | N | 0.76% | 0.69% | — | 0.000 |
| None | DOT_USD | BUY | 0.8263 | Y | N | 0.69% | 0.76% | — | 0.467 |
| None | DOT_USD | SELL | 0.8265 | N | N | 0.79% | 0.67% | — | 0.000 |
| None | BTC_USD | BUY | 64393.0100 | Y | Y | 2.18% | 0.14% | — | 0.804 |
| None | BTC_USD | BUY | 64393.0100 | Y | Y | 1.39% | 0.14% | — | 0.803 |
| None | BTC_USD | BUY | 64352.0800 | Y | Y | 2.25% | 0.07% | — | 0.804 |
| None | BTC_USD | BUY | 64352.0800 | Y | Y | 1.46% | 0.07% | — | 0.803 |
| None | ETH_USDT | BUY | 1697.3200 | Y | Y | 10.26% | 0.00% | Y | 0.865 |
| None | ETH_USDT | BUY | 1699.2000 | Y | Y | 10.48% | 0.00% | Y | 0.866 |
| None | ETH_USDT | BUY | 1699.8900 | Y | Y | 10.44% | 0.00% | Y | 0.866 |
| None | ETH_USDT | BUY | 1880.6700 | N | N | 0.00% | 1.34% | — | 0.000 |
| None | ETH_USD | BUY | 1876.7300 | N | N | 0.00% | 1.19% | — | 0.000 |
| None | ETH_USDT | BUY | 1826.7000 | Y | Y | 1.29% | 0.00% | — | 0.803 |

## Notes

- Offline only; OHLCV re-fetched from public Binance (or fixture).
- No secrets written; no HostSwapHigh / trading_config / Auto UI changes.
- Design: `docs/project-history/alert-quality-eval-phase1-2026-07-22.md`
