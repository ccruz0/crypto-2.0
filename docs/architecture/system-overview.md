# System Overview

Single source of truth for the Automated Trading Platform architecture and data flow.

---

## Purpose

The platform automates trading on Crypto.com Exchange: it monitors market signals, manages alerts (Telegram), places and tracks orders, and syncs state with the exchange. **Production runs only on AWS**; local setup is for development only.

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        AWS EC2 (PROD)                             │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐  ┌──────────┐ │
│  │   Nginx     │  │  Backend    │  │  Frontend   │  │   DB     │ │
│  │  (reverse   │  │  (FastAPI)  │  │  (Next.js)  │  │(Postgres)│ │
│  │   proxy)    │  │             │  │             │  │          │ │
│  └──────┬──────┘  └──────┬──────┘  └─────────────┘  └────┬─────┘ │
│         │                │                               │       │
│         │         SignalMonitorService, ExchangeSync,    │       │
│         │         TelegramNotifier, CryptoComTrade       │       │
│         │                │                               │       │
└─────────┼────────────────┼───────────────────────────────┼───────┘
          │                │                               │
          ▼                ▼                               │
   dashboard.hilovivo.com  Crypto.com Exchange API          │
   / → frontend            (orders, balance, history)      │
   /api/ → backend                                          │
```

- **Production**: atp-rebuild-2026 (single EC2). Dashboard: https://dashboard.hilovivo.com
- **Backend**: FastAPI, Gunicorn; no `uvicorn --reload` in production
- **Database**: PostgreSQL in Docker; not exposed publicly
- **Exchange**: Direct connection from backend to Crypto.com API (AWS Elastic IP whitelisted)

---

## Core Services (Backend)

| Service | File | Responsibility |
|---------|------|----------------|
| **SignalMonitorService** | `backend/app/services/signal_monitor.py` | Orchestrator: monitors signals, creates orders, lifecycle |
| **ExchangeSyncService** | `backend/app/services/exchange_sync.py` | Syncs exchange data, SL/TP, order execution events |
| **SignalThrottle** | `backend/app/services/signal_throttle.py` | Alert/trade throttling (price change, cooldown) |
| **StrategyProfiles** | `backend/app/services/strategy_profiles.py` | Strategy type (swing/intraday/scalp), risk (conservative/aggressive) |
| **TradingSignals** | `backend/app/services/trading_signals.py` | BUY/SELL signals from technical indicators |
| **TelegramNotifier** | `backend/app/services/telegram_notifier.py` | Alerts and notifications to Telegram |
| **CryptoComTrade** | `backend/app/services/brokers/crypto_com_trade.py` | Exchange API client |

---

## Data Flow (Order Lifecycle)

1. **Monitor** → SignalMonitorService runs on an interval; fetches market data, computes signals.
2. **Signal** → BUY/SELL from TradingSignals; strategy from StrategyProfiles.
3. **Alert** (optional) → If alerts enabled, throttle checked; Telegram notification sent.
4. **Order** → Primary order placed via CryptoComTrade; SL/TP created as needed.
5. **Sync** → ExchangeSyncService syncs open orders and history; resolves EXECUTED vs CANCELED from exchange (never assume “missing from open orders” = canceled).
6. **Events** → ORDER_EXECUTED / ORDER_CANCELED emitted only after confirmation from exchange.

Critical rule: **"Order not found in Open Orders" ≠ "Order canceled"**. Final state must be resolved via exchange order/trade history.

---

## Main Components (Summary)

- **API**: `/api/health`, `/api/monitoring/summary`, `/api/open-orders`, `/api/executed-orders`, etc.
- **Models**: WatchlistItem, ExchangeOrder, SignalThrottleState, TradeSignal.
- **Runtime**: Docker Compose with profile `aws`; all production operations via SSH (or SSM) on EC2.

---

## Related Docs

- [System map](system-map.md) — AI-readable map of components, APIs, data flow (start here for agents).
- [SYSTEM_MAP.md](../SYSTEM_MAP.md) — Detailed system map and order lifecycle
- [ORDER_LIFECYCLE_GUIDE.md](../ORDER_LIFECYCLE_GUIDE.md) — User-facing order lifecycle
- [Infrastructure (AWS)](../infrastructure/aws-setup.md)
- [Infrastructure (Docker)](../infrastructure/docker-setup.md)
- [Agent context](../agents/context.md) — How agents should work in this repo.
