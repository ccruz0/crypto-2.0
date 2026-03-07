# Trading Strategy

Overview of strategy logic, signals, and risk used by the Automated Trading Platform.

---

## Strategy Types

The platform supports configurable strategy profiles:

| Type | Description |
|------|-------------|
| **Swing** | Longer-term; larger moves, fewer trades |
| **Intraday** | Day trading; medium horizon |
| **Scalp** | Short-term; smaller moves, more frequent |

Strategy is resolved per watchlist item via **StrategyProfiles** (`backend/app/services/strategy_profiles.py`).

---

## Risk Approach

- **Conservative** — Tighter thresholds, lower size, more caution.
- **Aggressive** — Looser thresholds, higher size, more exposure.

Risk approach is combined with strategy type to drive signal and order behavior.

---

## Signals

- **TradingSignals** (`backend/app/services/trading_signals.py`) computes BUY/SELL from technical indicators (e.g. RSI, MAs, volume).
- **SignalMonitorService** runs on a configurable interval (e.g. 30s), fetches market data, and calls `calculate_trading_signals()`.
- Output: `buy_signal`, `sell_signal`, and strategy context for alerts and orders.

---

## Throttling (Alerts and Trades)

- **SignalThrottle** (`backend/app/services/signal_throttle.py`) limits alert and trade frequency.
- Checks:
  - **Price change threshold** (e.g. default 1.0%) — avoid duplicate alerts for tiny moves.
  - **Cooldown** (e.g. 60s) — minimum time between signals for the same symbol/strategy/side.
- Blocked events are logged (e.g. `SKIP_COOLDOWN_ACTIVE`, `SKIP_PRICE_CHANGE_INSUFFICIENT`) and recorded in throttle state for auditing.

---

## Order Roles

- **PRIMARY** — Main buy/sell from a trading signal.
- **TAKE_PROFIT (TP)** — Profit-taking order linked to a primary order.
- **STOP_LOSS (SL)** — Risk order linked to a primary order.

TP/SL execution can close positions; Telegram and sync logic reflect role when known.

---

## Related Docs

- [System overview](../architecture/system-overview.md)
- [Crypto.com order formatting](../trading/crypto_com_order_formatting.md) (if present)
- [Strategy settings flow](../STRATEGY_SETTINGS_FLOW_MAP.md) (if present)
- Backend: `backend/app/services/strategy_profiles.py`, `trading_signals.py`, `signal_throttle.py`
