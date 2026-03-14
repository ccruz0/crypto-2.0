# Market Data Flow Deep Dive

## 1. Purpose

This document maps the **end-to-end market data path** in the Automated Trading Platform and identifies **likely failure points** that could explain stale market data or updater stoppage. It also lists **minimal hardening opportunities** without proposing broad rewrites. Implementation of any hardening follows the Motion / OpenClaw / Cursor workflow and is out of scope for this analysis.

## 2. Components Involved

| Component | Type | Repo path / location | Role |
|-----------|------|----------------------|------|
| Exchange APIs | External | Crypto.com, Binance (price_fetcher), etc. | Source of prices and OHLCV |
| market_updater.py | Python module | backend/market_updater.py | Fetches from APIs, computes indicators, writes MarketPrice + MarketData + JSON cache |
| run_updater() | Async loop | backend/market_updater.py (run_updater) | 60s loop; calls update_market_data(); record_heartbeat() |
| run_updater.py | Entrypoint | backend/run_updater.py | asyncio.run(run_updater()) |
| market-updater-aws | Docker service | docker-compose (profile aws) | Runs run_updater.py in container |
| MarketPrice, MarketData | DB models | backend/app/models/market_price.py | Storage for prices and indicators; health uses MarketPrice.updated_at |
| system_health.py | Backend service | backend/app/services/system_health.py | _check_market_data_health(), _check_market_updater_health(); builds /api/health/system |
| /api/health/system | API | backend/app/api/routes_monitoring.py | Returns market_data + market_updater status |
| /api/market/update-cache | API | backend/app/api/routes_market.py | POST; calls update_market_data() in-process (used by remediation) |
| verify.sh | Script | scripts/selfheal/verify.sh | GET /api/health/system; PASS only if market_data and market_updater PASS |
| health_snapshot_log.sh | Script | scripts/diag/health_snapshot_log.sh | Writes verify + /api/health/system to /var/log/atp/health_snapshots.log |
| health_snapshot_telegram_alert.sh | Script | scripts/diag/health_snapshot_telegram_alert.sh | Reads snapshot log; streak_fail_3 / updater_age_gt5_3runs → remediation + Telegram |
| remediate_market_data.sh | Script | scripts/selfheal/remediate_market_data.sh | Restart market-updater-aws → sleep 10 → POST /api/market/update-cache (300s, retry) → optional health/fix |
| atp-health-snapshot.timer | systemd | scripts/selfheal/systemd/ | Runs health_snapshot_log.sh every 5 min |
| atp-health-alert.timer | systemd | scripts/selfheal/systemd/ | Runs health_snapshot_telegram_alert.sh every 5 min |
| atp-selfheal.timer | systemd | scripts/selfheal/systemd/ | Runs verify.sh → heal.sh (full stack); not market-data-specific |
| ExchangeSyncService | Backend service | backend/app/services/exchange_sync.py | Syncs exchange data every 5s to backend state; does **not** write MarketPrice (health uses MarketPrice) |
| routes_market.py, routes_dashboard.py | API | backend/app/api/ | Dashboard and market endpoints; read MarketData / MarketPrice / price_fetcher |
| SignalMonitorService | Backend service | backend/app/services/signal_monitor.py | Reads market data for signals (MarketData / watchlist) |

## 3. End-to-End Flow

```
Source (Exchange APIs)
  ↓
market_updater.py (update_market_data) — in container market-updater-aws, every 60s
  ↓
Writes: MarketPrice.updated_at, MarketData, JSON cache
  ↓
Validation: /api/health/system uses MarketPrice.updated_at for watchlist symbols
  ↓
Storage/state: PostgreSQL (MarketPrice, MarketData); health threshold default 30 min
  ↓
Consumers: SignalMonitorService, routes_market (dashboard, top-coins-data), routes_dashboard
  ↓
Health signals: verify.sh → GET /api/health/system → market_data.status, market_updater.status
  ↓
health_snapshot_log.sh → log; health_snapshot_telegram_alert.sh → streak rule → remediate_market_data.sh
```

- **market_updater status** is **inferred**: backend has no process check. `_check_market_updater_health()` uses `market_data.max_age_minutes` as a heartbeat proxy: if `max_age_minutes < stale_threshold_minutes` → PASS (is_running=True), else FAIL.
- **Remediation**: restart market-updater-aws container, then POST /api/market/update-cache (runs update_market_data() inside the **backend** process, 300s timeout + retry). No health/fix before update-cache (to avoid backend restart interrupting the long POST).

## 4. Freshness and Staleness Model

- **Freshness:** Represented by `MarketPrice.updated_at` (and optionally MarketData.updated_at). Health checks use **MarketPrice** for watchlist symbols only (or market_prices fallback when watchlist is empty).
- **Stale threshold:** Default **30 minutes** (`HEALTH_STALE_MARKET_MINUTES`, backend env). Data older than that is “stale.”
- **Where staleness is detected:**
  - **Backend:** `_check_market_data_health()` in system_health.py: for each watchlist symbol, compares `MarketPrice.updated_at` to `now - stale_threshold`; counts fresh vs stale; PASS if at least one fresh, FAIL if all stale, WARN if some stale.
  - **Backend:** `_check_market_updater_health()`: no direct process check; uses `market_data.max_age_minutes`; if `max_age_minutes < stale_threshold_minutes` → updater PASS, else FAIL.
  - **Updater (internal):** market_updater.py logs a warning when *all* MarketPrice rows are older than 30 min (and can call system_alerts); does not change health endpoint.
- **Updater age:** “Updater age” in alerts is the same as data age (max_age_minutes). There is an optional Prometheus gauge `market_updater_heartbeat_age_seconds` updated by the updater process, but **/api/health/system does not use it**; it relies only on DB freshness.
- **Threshold application:** Single global threshold (30 min default). No per-symbol or per-consumer thresholds in health.

## 5. Failure Modes

| Failure | What fails | How it would appear | How it is detected | How it is remediated |
|---------|------------|---------------------|--------------------|----------------------|
| **Upstream API failure** | Exchange unreachable or errors | Updater logs errors; update_market_data() may skip or partial write; MarketPrice.updated_at stops advancing for some/all symbols | After threshold: health sees all symbols stale → market_data FAIL, market_updater FAIL | remediate_market_data: restart container + update-cache. If exchange is still down, update-cache can fail or write nothing; next cycle will again age. |
| **Rate limiting** | Exchange throttles requests | Update cycle takes longer; fewer symbols updated per 60s; data age can grow | Same as above (eventual 30 min FAIL) | Same; restart does not fix rate limit. |
| **Updater process crash** | Container or process exits | No writes to MarketPrice; updated_at freezes | After 30 min: market_data FAIL, market_updater FAIL (inferred from max_age) | remediate_market_data: restart container + update-cache. First update-cache run can be slow (up to 300s). |
| **Container restart without recovery** | Container restarts (OOM, deploy) but no one triggers update | Same as crash: no new writes until next run or remediation | 30 min delay then FAIL | atp-selfheal (heal.sh) restarts stack; or health-alert remediation restarts updater + update-cache. |
| **Data validation failure** | DB error, constraint, or exception in update_market_data() | Updater logs exception; loop continues after 60s sleep; may or may not write | If no successful write for any symbol, 30 min later FAIL | Remediation restarts container and runs update-cache; if backend/DB is unhealthy, update-cache can return empty or 5xx. |
| **State not updating** | DB connection lost from updater, or wrong DB | Writes never commit; health still sees old timestamps | 30 min then FAIL | Restart + update-cache; update-cache runs in backend so uses backend’s DB connection. |
| **Health signal delay** | Snapshot every 5 min; streak rule (e.g. streak_fail_3) | verify.sh fails 3 times in a row before remediation runs | Detection: 30 min (stale) + up to 15 min (3 × 5 min) = **up to ~45 min** until remediation starts | N/A (inherent delay). |
| **Overly broad remediation** | heal.sh (full stack restart) runs | Backend restarts; in-flight update-cache or health checks can get empty reply | Transient FAIL; remediate_market_data is narrower (updater + update-cache only, no health/fix before cache) | Current design avoids health/fix before update-cache to reduce this. |

## 6. Current Gaps

- **Long stale threshold (30 min):** Stale data can persist for up to 30 minutes before health flips to FAIL. Combined with 5 min snapshot and streak rule, remediation can start ~45 min after the updater actually stopped.
- **No direct updater heartbeat in health:** Backend does not check whether the updater process is running; it infers “updater running” from “data fresh.” If the updater hangs without exiting (e.g. stuck on network), health stays PASS until data ages past 30 min.
- **update-cache runs in backend:** Remediation calls POST /api/market/update-cache, which runs update_market_data() inside the backend process. If the backend is slow or unhealthy, update-cache can time out (300s) or return empty/5xx; remediation then relies on the restarted container’s own 60s loop to eventually write again.
- **Single source of truth for health:** MarketPrice.updated_at (watchlist symbols) is the only input for both market_data and market_updater status. No fallback to Prometheus heartbeat or process check.
- **No consumer-side staleness guard:** Signal and dashboard consumers can read whatever is in the DB; there is no documented “max age” check before using data for signals (beyond health’s 30 min for reporting).

## 7. Minimal Hardening Opportunities

- **Earlier stale detection:** Reduce delay by lowering the effective staleness threshold (e.g. configurable 10–15 min via HEALTH_STALE_MARKET_MINUTES) so FAIL is raised sooner. Trade-off: more false FAILs if a single slow cycle exceeds the threshold.
- **Clearer updater heartbeat:** Expose a dedicated “last successful write” or “last updater heartbeat” in /api/health/system (e.g. from Prometheus gauge or a small table/endpoint the updater updates). Keeps remediation logic unchanged but makes “updater running” explicit instead of inferred from data age.
- **Narrower remediation scope:** Already narrow (remediate_market_data: restart updater + update-cache only). Optional: document that atp-selfheal (full stack) should not be the first response to market_data FAIL when only market data is affected.
- **Fallback source logic:** Health already has market_prices fallback when watchlist is empty. Consumers (e.g. dashboard) already use MarketData → MarketPrice → price_fetcher priority. Optional: document a simple “degraded” mode when market_data is WARN (e.g. show “data may be delayed” or avoid trading decisions on stale symbols).
- **Consumer degradation rules:** Document or add a simple rule: if market_data.status is FAIL or max_age > N minutes, signal monitor could treat affected symbols as “no signal” or skip order placement until data is fresh (would require a small, scoped code path; not a broad rewrite).

## 8. Recommended Next Deep-Dive

**Single best next technical follow-up:** **Staleness threshold and alert timing.** Define a concrete recommendation for HEALTH_STALE_MARKET_MINUTES (and, if used, alert rule thresholds such as updater_age_gt5) and document the end-to-end delay from “updater stopped” to “remediation started.” Optionally add a one-page “market data health decision tree” (when FAIL vs WARN, when to remediate vs when to alert only) so operators and future automation have a single reference.

## 9. Evidence Appendix

| Item | Path / reference |
|------|-------------------|
| Market data health (market_data + market_updater) | backend/app/services/system_health.py: _check_market_data_health, _check_market_updater_health, get_system_health |
| Stale threshold env | HEALTH_STALE_MARKET_MINUTES (default 30) in system_health.py |
| Health endpoint | backend/app/api/routes_monitoring.py: get_system_health_endpoint → get_system_health(db) |
| verify.sh logic | scripts/selfheal/verify.sh: jq .market_data.status, .market_updater.status; PASS/DEGRADED/FAIL |
| Remediation script | scripts/selfheal/remediate_market_data.sh: docker compose restart market-updater-aws, POST update-cache |
| Alert + remediation flow | scripts/diag/health_snapshot_telegram_alert.sh: RULE streak_fail_3, is_market_incident, remediate_market_data.sh |
| Updater loop and heartbeat | backend/market_updater.py: run_updater() 60s loop, record_heartbeat(), Prometheus gauge market_updater_heartbeat_age_seconds |
| update-cache endpoint | backend/app/api/routes_market.py: POST /market/update-cache → update_market_data() |
| MarketPrice/MarketData writes | backend/market_updater.py: update_market_data(), MarketPrice.updated_at, MarketData.updated_at |
| Runbook | docs/runbooks/EC2_FIX_MARKET_DATA_NOW.md |
| Architecture task scope | docs/ARCHITECTURE_TASK_MARKET_DATA_FLOW_DEEP_DIVE.md |
| Solution architecture (flow summary) | docs/SOLUTION_ARCHITECTURE_MASTER.md §5 |
| Signal flow (data sources) | docs/monitoring/signal_flow_overview.md |
| Canonical recovery / remediation | docs/CANONICAL_RECOVERY_RESPONSIBILITY_MAP.md, docs/CANONICAL_MECHANISM_INVENTORY.md |
