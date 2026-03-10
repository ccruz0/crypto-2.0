# ATP Improvements from OpenClaw Research (2026)

This document maps the research summary from OpenClaw’s web search to the current ATP codebase: what we already have, what’s optional, and what to do next.

---

## 1. Architecture improvements

| Research suggestion | ATP status | Notes |
|---------------------|------------|--------|
| **FastAPI high performance** | ✅ In place | FastAPI backend; Prometheus metrics and slow-request logging in `main.py`. |
| **Connection pooling** | ✅ In place | `backend/app/database.py`: SQLAlchemy pool (e.g. `pool_size=10`, `max_overflow=20`, `pool_pre_ping`, `pool_recycle`). Sync engine, not async. |
| **WebSocket for live trading data** | ✅ Implemented | **Outbound:** Crypto.com WebSocket client for orders/balances. **Inbound:** `/api/ws/prices` streams cached prices (from Crypto.com get-tickers) to the dashboard. See `price_stream.py` and `routes_ws_prices.py`. Env: `ENABLE_WS_PRICES`, `PRICE_STREAM_INTERVAL_S`. |
| **Decentralized / microservices** | 🔮 Future | Single backend today; optional later if we split trading vs. dashboard vs. agents. |

**Done:** `/api/ws/prices` streams price updates to the dashboard; frontend can subscribe and keep polling as fallback.

---

## 2. Agent orchestration (Notion, etc.)

| Research suggestion | ATP status | Notes |
|---------------------|------------|--------|
| **Notion API integration** | ✅ In place | `notion_tasks.py`, `notion_task_reader.py`; agent reads/writes tasks. |
| **Notion native AI agents (Feb 2026)** | 📋 Research | Good candidate for a later phase: evaluate when to migrate from polling + our agent to Notion’s native agents. |
| **Zapier / no-code workflows** | 🔮 Optional | Could complement Notion for external integrations; not required for current scope. |

**Action:** Proceed with current Notion integration; track Notion AI agents for a future migration (Phase 2 in the research summary).

---

## 3. Production deployment

| Research suggestion | ATP status | Notes |
|---------------------|------------|--------|
| **Docker Compose** | ✅ In place | `docker-compose.yml` with profiles (e.g. `local`, `aws`); backend, frontend, db, etc. |
| **Health checks** | ✅ In place | `/health`, `/api/health`, `/api/health/system`; Docker `healthcheck` on backend; smoke checks in `deploy_smoke_check.py`. |
| **Replicas / resource limits** | ✅ Limits in place | Backend AWS: `memory: 2G`, `cpus: 1.0`. Frontend AWS: `memory: 512M`. Replicas deferred until Swarm/K8s. |

**Done:** Backend-aws memory set to 2G in `docker-compose.yml`. Nginx: dedicated `location ^~ /api/ws/` with WebSocket headers in `nginx/dashboard.conf` and `dashboard-local.conf` so `/api/ws/prices` works through the proxy.

---

## 4. Technical stack validation

| Item | Status |
|------|--------|
| FastAPI + PostgreSQL | ✅ |
| Docker Compose for deployment | ✅ |
| Notion API | ✅ |
| OpenClaw (separate repo) | ✅ Docs and scripts in `docs/openclaw/`, `scripts/openclaw/`. |

No change needed; stack matches 2026-style recommendations.

---

## 5. Immediate action items (prioritized)

1. **Complete current deployment (orchestration)**  
   Use existing runbooks and smoke checks; no doc change needed.

2. **Performance monitoring**  
   Already in place: health endpoints, Prometheus middleware, `/api/health/system`. Optional: add a short “Performance benchmarks” section to this doc and record baseline targets (e.g. &lt;10 ms for `/health`, &lt;100 ms for exchange calls).

3. **Research Notion AI agents**  
   Document in a short “Notion roadmap” note: Phase 2 = evaluate Notion native agents when stable and beneficial.

4. **WebSocket trading feeds for dashboard** ✅ **Done**  
   - **Backend:** `/api/ws/prices` (see `routes_ws_prices.py` + `price_stream.py`). Cache updated every `PRICE_STREAM_INTERVAL_S` from `get_crypto_prices()`; clients get snapshot on connect and periodic updates.  
   - **Frontend:** `PriceStreamContext` + `usePriceStream()` in `app/context/PriceStreamContext.tsx`; Watchlist tab uses live prices when connected and shows a live indicator. Polling remains as fallback.  
   - Env: `ENABLE_WS_PRICES=true` (default), `PRICE_STREAM_INTERVAL_S=10`.

5. **Scale testing**  
   Optional later: load testing (e.g. `locust` or `k6`) against `/api/health` and main trading endpoints to validate “&lt;10 ms” and concurrency assumptions.

---

## 6. Performance benchmarks (targets)

From the research; use as targets, not yet enforced:

- **API response time:** &lt; 10 ms for simple endpoints (e.g. `/health`).
- **Concurrent orders:** Design for 1000+ (PostgreSQL and pool support it; validate with tests).
- **Trading latency:** &lt; 100 ms exchange response (depends on exchange and network).
- **Uptime:** 99.9% with current health checks and monitoring.

---

## 7. What we are **not** doing (for now)

- **asyncpg:** DB is SQLAlchemy sync with pooling; switching to async PG would be a larger refactor. Defer unless we need async for other reasons.
- **Kubernetes:** Staying on Docker Compose for single-server deployment; K8s only if we move to multi-server.
- **Multiple backend replicas in Compose:** Compose doesn’t load-balance replicas by default; leave single replica until we introduce an orchestrator or load balancer.

---

## 8. Next steps (concise)

1. **Now:** Finish any in-flight orchestration/deployment; verify `/api/ws/prices` and live prices on the dashboard (nginx must proxy WebSocket for `/api/` if needed).  
2. **Short term:** ✅ Resource limits and nginx WebSocket for `/api/ws/` are in place. On the server, reload nginx after pulling (e.g. `sudo nginx -t && sudo systemctl reload nginx`).  
3. **Optional:** Use `usePriceStream()` in other tabs (e.g. Portfolio, Expected TP) for live price overlay where useful.  
4. **Backlog:** Notion AI agents evaluation; optional load testing and benchmark logging.

This file is the single reference for “what the research means for ATP” and what to implement next. OpenClaw (or Cursor) can use it to avoid suggesting work already done or out of scope.
