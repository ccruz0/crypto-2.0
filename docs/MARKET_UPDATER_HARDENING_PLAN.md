# Market Updater Hardening Plan

## 1. Purpose

This document defines the **smallest safe hardening steps** to improve detection of market-updater failure, based on the findings in the Market Data Flow Deep Dive. **Candidate A (configurable earlier stale detection) is implemented.** Candidate B (explicit updater heartbeat) is not yet implemented. Any further implementation will follow the Motion / OpenClaw / Cursor workflow and remain minimal, production-safe, and reversible.

## 2. Current Situation

- **Staleness model:** Health uses `MarketPrice.updated_at` (watchlist symbols) and a single global threshold. Default threshold is **30 minutes** (`HEALTH_STALE_MARKET_MINUTES`). `market_updater` status is **inferred** from data freshness only (no process or heartbeat check).
- **Why detection is too slow:** When the updater stops or hangs, no new writes occur. Health flips to FAIL only after data age exceeds 30 min. With snapshot every 5 min and a streak rule (e.g. streak_fail_3), remediation can start **up to ~45 minutes** after the updater actually stopped. That delay increases the window where signals and dashboard may use stale data.

## 3. Hardening Candidate A: Earlier Stale Detection

- **Current threshold behavior:** Backend `_check_market_data_health()` and `_check_market_updater_health()` use `stale_threshold_minutes` from env `HEALTH_STALE_MARKET_MINUTES` (default 30). Same value is used for both market_data and market_updater. No override today in runbooks or deploy.
- **Proposed:** Make the threshold **configurable** via existing (or clearly documented) env and set a **stricter default or a documented recommended value** for production so that “stale” is detected earlier.
- **Suggested value range:** **10–15 minutes.** Rationale: updater runs every 60s; a few missed cycles (e.g. 5–10 min) already indicate a problem; 10–15 min gives a small buffer for one slow cycle or brief blip without waiting 30 min.
- **Benefits:** Shorter time from “updater stopped” to FAIL, so alert and remediation can run sooner. No new components; only threshold and possibly env/docs.
- **Risks / false positive trade-offs:** A single very slow update cycle (e.g. many symbols, rate limit, or transient DB slowness) could push max_age over 10–15 min and trigger FAIL + remediation even though the updater is still running. Mitigation: keep value configurable so it can be relaxed if false FAILs appear; document the trade-off in runbooks.
- **Code/config areas likely to review:** `backend/app/services/system_health.py` (where `HEALTH_STALE_MARKET_MINUTES` is read and used); deploy/secrets or runbooks that set env for backend; docs that describe “stale” and recommended production value.

**Implementation (done):** The threshold is read from env `HEALTH_STALE_MARKET_MINUTES`; invalid or missing values fall back to 30. Parsing is in `_parse_stale_market_minutes()` (valid range 1–1440 minutes). **Recommended production value:** `HEALTH_STALE_MARKET_MINUTES=15`.

## 4. Hardening Candidate B: Explicit Updater Heartbeat

- **Why inferring from DB age is indirect:** Health has no signal that the updater **process** is alive. It only observes that “newest data is recent.” If the updater hangs without exiting (e.g. stuck on network or a long-running call), it might still be “running” but not writing; we only notice when data ages past the threshold. Conversely, data could be updated by something else (e.g. a one-off update-cache call), and health would report updater PASS even if the container is dead.
- **What a heartbeat would make clearer:** A dedicated “last successful updater activity” signal (e.g. “last write time” or “last heartbeat time”) would separate “data is fresh” from “updater is alive and writing.” Health could then report updater FAIL when heartbeat is too old even if some data is still fresh (e.g. from a recent manual update-cache).
- **Likely implementation shapes:** (1) **DB-based:** Updater writes a single row or key (e.g. “last_heartbeat” table or key-value) on each successful loop; backend health reads it. (2) **Existing Prometheus gauge:** The updater already updates `market_updater_heartbeat_age_seconds`; backend could expose an optional health check that uses this metric if available, or a small sidecar that reads it and writes to a place the backend can read. (3) **Lightweight endpoint:** Updater (or a side process) POSTs a timestamp to the backend on each cycle; backend stores it and health compares to now. Any shape should be minimal and not add heavy new infrastructure.
- **Benefits:** Clearer “updater running” signal; earlier detection of hung-but-not-crashed updater; ability to distinguish “no data” from “no heartbeat.”
- **Added complexity:** New write path (updater or sidecar), new read path in health, and possibly new failure modes (e.g. heartbeat write fails). Should be scoped to a single, small change set.

## 5. Recommended Order

1. **Configurable earlier stale detection** — Lower effective threshold (e.g. 10–15 min) via existing or documented env; no new services or heartbeat logic. Reversible by changing env back to 30.
2. **Updater heartbeat** — Add an explicit heartbeat and use it in health after (1) is in place and stable. Keeps changes ordered and limits blast radius.

Do not propose larger changes (new fallback sources, consumer redesign, or broad health refactors) in this plan.

## 6. Verification Requirements

**Candidate A (earlier stale detection):**

- **Expected detection behavior:** When updater is stopped, health should transition to market_data FAIL / market_updater FAIL within the new threshold (e.g. 10–15 min) instead of 30 min.
- **Expected alert timing:** Snapshot + streak rule should trigger remediation/Telegram within roughly threshold + (2–3 × 5 min) after last write.
- **Expected remediation timing:** remediate_market_data.sh should run sooner after a real updater failure.
- **Rollback:** Set `HEALTH_STALE_MARKET_MINUTES` back to 30 (or previous value); restart backend so it picks up env; no code rollback required if only env/default changed.

**Candidate B (explicit heartbeat):**

- **Expected detection behavior:** When updater is stopped or hung, health should report market_updater FAIL when heartbeat age exceeds a defined limit (e.g. 5–10 min), independent of or in addition to data age.
- **Expected alert timing:** Same as today for alerts that key off health; potentially earlier if heartbeat is checked more aggressively than data age.
- **Expected remediation timing:** Same remediation path (remediate_market_data.sh); no change to remediation logic in this plan.
- **Rollback:** Disable or bypass heartbeat in health (e.g. feature flag or fallback to current “infer from data” behavior); optionally stop updater from writing heartbeat. No removal of existing health logic until heartbeat path is proven.

## 7. Implementation Constraints

- **No broad rewrite** — Do not refactor the whole health or market-data pipeline.
- **No new fallback source work yet** — Do not add new data sources or fallback chains as part of this hardening.
- **No consumer redesign yet** — Do not change how SignalMonitorService or dashboard consume market data; only improve **detection** of updater failure.
- **Minimal localized changes only** — Limit changes to: (A) threshold configuration and possibly default in system_health.py and env/docs; (B) one small heartbeat write (updater or sidecar) and one small read in health, with clear rollback.

## 8. Recommended Next Implementation Task

**Single best next implementation task:** **Make stale threshold configurable and set a production-recommended value (Candidate A).**

**Why:** It requires no new services, no new write paths, and no change to the updater binary. Only the backend (and optionally deploy/runbook docs) need to respect `HEALTH_STALE_MARKET_MINUTES` and use a lower value (e.g. 15) in production. Rollback is a config change. Once this is live and observed (fewer minutes to detection, acceptable false-positive rate), adding an explicit heartbeat (Candidate B) has a clear baseline and a smaller risk of overlapping behavior changes.

## 9. Evidence

- **Primary analysis:** docs/MARKET_DATA_FLOW_DEEP_DIVE.md (sections 4–7: freshness model, failure modes, gaps, minimal hardening).
- **Relevant repo areas:**  
  - `backend/app/services/system_health.py` — `_check_market_data_health()`, `_check_market_updater_health()`, `get_system_health()`; `HEALTH_STALE_MARKET_MINUTES`, `HEALTH_MONITOR_STALE_MINUTES`.  
  - `backend/market_updater.py` — `run_updater()`, `record_heartbeat()`, Prometheus gauge `market_updater_heartbeat_age_seconds`.  
  - `scripts/selfheal/verify.sh` — uses `/api/health/system` output.  
  - `scripts/diag/health_snapshot_telegram_alert.sh` — streak rule and remediation trigger.  
  - `scripts/selfheal/remediate_market_data.sh` — restart updater + POST update-cache.

## 10. Candidate A: Verification and Rollback

### How to confirm current effective threshold

The backend does not expose the threshold in the health JSON. To confirm what value is in use:

1. **From the host where the backend runs** (e.g. EC2), ensure the backend process has the intended env. If using Docker and `secrets/runtime.env` or `env_file`:
   ```bash
   # Optional: list env keys only (no values) for backend container
   docker compose --profile aws exec backend-aws env 2>/dev/null | grep -E '^HEALTH_STALE' || echo "HEALTH_STALE_MARKET_MINUTES not set (using default 30)"
   ```
2. **Infer from behavior:** With updater stopped, health will flip to market_data FAIL / market_updater FAIL after **threshold minutes**. Default is 30; if you set 15, it will flip after ~15 minutes.

### How to test with 15

1. Set the variable for the backend (e.g. in `secrets/runtime.env` or in the compose `environment` for backend-aws):
   ```bash
   echo 'HEALTH_STALE_MARKET_MINUTES=15' >> secrets/runtime.env
   ```
2. Restart the backend so it picks up the new env:
   ```bash
   docker compose --profile aws up -d backend-aws
   ```
3. Confirm health still PASS while updater is running. Optionally stop the market-updater container and observe that health goes FAIL within ~15 min (and snapshot/alert/remediation follow).

### Exact rollback step

To revert to the previous behavior (30-minute threshold):

1. Remove or override the variable so the backend uses the default 30:
   - **If you added it to `secrets/runtime.env`:** Remove the line `HEALTH_STALE_MARKET_MINUTES=15` (or set `HEALTH_STALE_MARKET_MINUTES=30`).
   - **If you set it in compose or elsewhere:** Remove the setting or set `HEALTH_STALE_MARKET_MINUTES=30`.
2. Restart the backend:
   ```bash
   docker compose --profile aws up -d backend-aws
   ```
3. No code rollback is required; the default in code is 30.

### Exact verification commands

- **Health endpoint (after backend restart):**  
  `curl -sS http://127.0.0.1:8002/api/health/system | jq '.market_data, .market_updater'`  
  When data is fresh, both should show `"status": "PASS"`. When data is older than the threshold, status will be FAIL.
- **Verify script (uses same health):**  
  `BASE=http://127.0.0.1:8002 ./scripts/selfheal/verify.sh`  
  Output will be PASS or e.g. `FAIL:MARKET_DATA:...` / `FAIL:MARKET_UPDATER:...` when stale.

### Production config step

**Automatic:** `scripts/aws/render_runtime_env.sh` now appends `HEALTH_STALE_MARKET_MINUTES=15` to `secrets/runtime.env`. Any deploy that runs the render script (e.g. before `docker compose --profile aws up`) will set the variable for backend-aws. After deploy, restart only the backend so it picks up the new env:

```bash
docker compose --profile aws up -d backend-aws
```

**Manual (PROD, if not re-rendering):** On the PROD host, add the variable to the existing runtime env, then restart only the backend:

```bash
cd /path/to/repo   # e.g. /home/ubuntu/crypto-2.0
grep -n 'HEALTH_STALE_MARKET_MINUTES' secrets/runtime.env || true
# If not present, add:
echo 'HEALTH_STALE_MARKET_MINUTES=15' | sudo tee -a secrets/runtime.env
sudo docker compose --profile aws up -d backend-aws
```

Then verify:

```bash
sudo docker compose --profile aws exec backend-aws env | grep '^HEALTH_STALE_MARKET_MINUTES='
curl -sS http://127.0.0.1:8002/api/health/system | jq '.market_data, .market_updater'
BASE=http://127.0.0.1:8002 ./scripts/selfheal/verify.sh
```

**What to watch:** Shorter threshold = faster detection, but more chance of false FAIL on slow cycles. After setting 15, observe for a few days: alert frequency, self-heal frequency, and any market-updater false alarms. Rollback: remove the line or set `HEALTH_STALE_MARKET_MINUTES=30`, then restart backend-aws.

---

**Summary:**  
- **File created:** docs/MARKET_UPDATER_HARDENING_PLAN.md  
- **Recommended first implementation:** Configurable earlier stale detection (Candidate A): make threshold configurable and set a production-recommended value (e.g. 10–15 min).  
- **Main trade-off to watch:** Shorter threshold may cause false FAILs when a single update cycle is legitimately slow (many symbols, rate limit, or DB delay); keep value configurable and document so it can be tuned or rolled back.
