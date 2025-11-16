# Automated Trading Platform – Project Overview

This project is an automated crypto trading platform with a unified frontend dashboard and a FastAPI backend. It orchestrates data ingestion (signals, balances, open orders), decision logic (e.g., RSI/MA/ATR based signals, SL/TP profiles), and trade execution (manual and automated), exposed through a JSON API and served publicly behind Nginx. The frontend consumes a single API base (`/api`) and renders a unified dashboard, portfolio, watchlist, orders, and live trading controls. A health monitoring suite (systemd timers + scripts) validates endpoint and dashboard health periodically and can notify on failures.

The platform runs in two profiles: local (development) and AWS (production). On AWS, services run via Docker Compose with `gluetun` for VPN outbound, `backend-aws` and `frontend-aws` containers, and a hardened Postgres. All remote operations and deployments use a unified SSH helper with an idempotent, DRY_RUN-capable toolchain for predictable and auditable changes. Nginx terminates TLS and proxies `/` to the frontend (port 3000) and `/api/*` to the backend (port 8002); `/api/health` is an exact-match that proxies to the backend `__ping`.

## Tech Stack and Major Components
- Frontend: Next.js/TypeScript, single API entry at `/api` (see `frontend/src/app/api.ts`).
- Backend: FastAPI (Python), SQLAlchemy + Postgres, service modules for signals, orders, scheduler.
- Infra: Docker Compose (local & AWS profiles), Nginx TLS reverse proxy, systemd timers for monitoring.
- VPN/Outbound privacy: `gluetun` container (AWS profile).
- Health/Monitoring: `scripts/health_monitor.sh`, dashboard health check timer, Telegram notifier.

## API Dependencies and Conventions
- API base: Frontend detects environment; on AWS/Nginx it uses the same host with `/api` prefix.
- Critical endpoints:
  - `GET /api/dashboard/state` – consolidated dashboard state (balances, signals, orders).
  - `GET /api/market/top-coins-data` – top coins data with indicators (RSI, MA, ATR).
  - `GET /api/trading/live-status` – current LIVE vs DRY mode.
  - `POST /api/trading/live-toggle` – toggle LIVE_TRADING; always returns JSON.
  - `GET /api/health` – proxied exact-match to backend `__ping`.
  - Orders: `GET /api/orders/open`, `GET /api/orders/history`, `POST /api/orders/quick`, `POST /api/manual-trade`.
- Auth/header: `x-api-key: demo-key` is sent by the frontend for API calls (adjust in production).
- Responses must ALWAYS be JSON. On errors return `{ ok:false, success:false, error:"..." }` with an appropriate HTTP status code.

## Naming / Structure Conventions
- Endpoints live under `/api/...` and must emit JSON. Do not return HTML or empty bodies.
- Frontend API helper: `frontend/src/app/api.ts` – one place for endpoint timeouts, error handling, circuit breaker for `/signals`.
- LIVE_TOGGLE flow:
  - Backend returns `{ ok:true, success:true, live_trading_enabled, mode }` (success) or `{ ok:false, success:false, error, mode }` (error).
  - Frontend reads `Response` exactly once (text → safe JSON parse fallback).
- SSH & Deploy:
  - Use `scripts/ssh_key.sh` only (defines `SSH_KEY`, `SSH_OPTS`, and `ssh_cmd/scp_cmd/rsync_cmd`).
  - Never call raw `ssh/scp/rsync` in scripts; use helpers.
  - All deploy scripts support `DRY_RUN=1`.

## Must-Not-Change Without Updating This File
- Nginx proxy rules:
  - `location = /api/health` must proxy to backend `__ping` before the general `/api` block.
  - General `/api` proxy to backend at port 8002 must remain JSON-only.
- Unified SSH helper location and contract: `scripts/ssh_key.sh` (functions and options).
- Frontend response handling rule: never read a `Response` stream more than once; parse body as text then safely JSON.parse.
- Backend contract for trading toggle/status: return the `success/ok` boolean keys and `mode` always.


