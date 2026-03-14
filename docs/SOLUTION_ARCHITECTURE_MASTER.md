# Solution Architecture Master

## 1. Purpose

The **Automated Trading Platform (ATP)** is a production system that automates crypto trading: it ingests market data, computes trading signals, places and tracks orders (including stop-loss and take-profit), and exposes a dashboard and APIs for operators. This document is the **master solution architecture**: it describes the platform’s purpose, current production baseline, architecture domains, canonical runtime layers, main data and control flows, and how development and operations are organized. It is the single reference for “how the system is built and run” and should stay aligned with the documented production baseline.

## 2. Current Production Baseline

The confirmed production stack is:

- **Infrastructure:** AWS EC2 instance, instance status checks, SSM access.
- **OS:** swap enabled, systemd services.
- **Runtime:** Docker containers, nginx reverse proxy.
- **Application monitoring:** atp-selfheal.timer, atp-health-alert.timer, atp-health-snapshot.timer.
- **External verification:** /api/health endpoint.

health_monitor.service is **not** installed on PROD; the runtime recovery stack is already aligned with the canonical responsibility map. EC2 auto-recovery is prepared; swap hardening and observability baseline are documented.

**Operational truth source:** For a single canonical list of health, recovery, and observability mechanisms and their PROD status, see **docs/CANONICAL_MECHANISM_INVENTORY.md**.

## 3. Architecture Domains

### Platform reliability

Infrastructure and runtime recovery, OS stability, and the separation between observation, notification, and remediation. Covers AWS EC2 recovery, swap, Docker, ATP timers, and the rule that only one mechanism performs runtime remediation (atp-selfheal.timer). See **docs/CANONICAL_RECOVERY_RESPONSIBILITY_MAP.md**.

### Trading engine

Signal calculation, throttle and eligibility checks, order placement, and post-order risk (SL/TP). Covers SignalMonitorService, trading_signals, exchange sync, and the invariant that a “sent” signal must lead to an order attempt (with only dedup blocking). See **docs/monitoring/signal_flow_overview.md**, **docs/monitoring/alert_to_order_flow.md**, **docs/SYSTEM_MAP.md**.

### Data and market services

Ingestion of market data from exchanges, storage (e.g. MarketData, MarketPrice), technical indicators, and feeding the signal and dashboard pipelines. Covers ExchangeSyncService, market updater, price fetcher, and database models.

### Monitoring and operator control

Health checks, snapshots, alerts, runbooks, and how operators inspect, verify, and intervene. Covers atp-health-snapshot (observation), atp-health-alert (notification), atp-selfheal (remediation), /api/health, Telegram, and operator runbooks.

### Delivery workflow

How changes are prioritized, analyzed, and implemented safely: Motion (task management), OpenClaw (technical analysis and change planning), Cursor (implementation). See **docs/OPERATING_MODEL_MOTION_OPENCLOW_CURSOR.md**.

## 4. Canonical Runtime Layers

| Layer | Owner | Responsibility |
|-------|--------|----------------|
| **AWS recovery** | AWS | Recover the instance if the host is unreachable (status checks, auto-recovery). |
| **OS stability** | OS / swap | Reduce OOM risk; swap configuration and safety margin in place. |
| **Docker runtime** | Docker / compose | Run application and supporting services; restart policies and healthchecks. |
| **ATP timers** | systemd | atp-selfheal (runtime remediation), atp-health-snapshot (observation), atp-health-alert (notification). |
| **External health endpoint** | Backend | /api/health for liveness/readiness used by external checks and load balancers. |
| **Human operations** | Operator | Runbooks, manual inspection, incident response when automation is insufficient. |

Only **atp-selfheal.timer** performs runtime remediation (e.g. restart Docker/stack); observation and alerting do not restart services.

## 5. Market Data Flow

End-to-end path from source to consumer:

1. **Source:** Exchange APIs (e.g. Crypto.com), optionally other sources via price_fetcher (e.g. Binance).
2. **Ingestion:** ExchangeSyncService (periodic sync, e.g. every 5s) and/or market updater process (update_market_data) pull prices and OHLCV, compute technical indicators (RSI, MAs, volume, etc.).
3. **Storage:** MarketData and MarketPrice (and related) tables store current price, indicators, and volume; watchlist and custom coins drive which instruments are updated.
4. **Consumers:**  
   - **Signal pipeline:** SignalMonitorService reads from MarketData for the monitoring loop (e.g. every 30s).  
   - **Dashboard/API:** routes_market.py and dashboard endpoints use MarketData → MarketPrice → price_fetcher priority for watchlist and top-coins.  
   - **Health/observability:** Snapshot and alert flows can use market data freshness as a signal (observation only).

Flow: **Exchange API → Sync/Updater → DB (MarketData/MarketPrice) → SignalMonitorService + routes_market + observability.**

## 6. Trading Execution Flow

End-to-end path from signal to order to tracking to exit:

1. **Signal:** SignalMonitorService loads market data per watchlist item, calls calculate_trading_signals() (trading_signals.py) with strategy rules from trading_config.json; outputs BUY/SELL/WAIT.
2. **Throttle and gates:** should_emit_signal() (time/price gates); then eligibility checks (alert_enabled, trade_enabled, trade_amount_usd, MAX_OPEN_ORDERS, cooldowns, LIVE_TRADING, portfolio limits). All checks happen **before** marking the signal as “sent.”
3. **Sent and order:** Once sent (Telegram + record_signal_event), only a dedup check may block; then _create_buy_order / _create_sell_order place a MARKET order via the exchange client (e.g. Crypto.com).
4. **Persistence and notification:** Order result is stored (ExchangeOrder, order_history_db); ORDER_CREATED / ORDER_FAILED events go to Telegram and throttle state.
5. **Post-order risk:** ExchangeSyncService creates SL/TP for filled orders (e.g. _create_sl_tp_for_filled_order), with fill confirmation via polling if needed.
6. **Tracking and exit:** Orders and positions are synced and tracked via exchange sync; exits occur via TP/SL or manual/runbook intervention.

Flow: **Market data → calculate_trading_signals → throttle + gates → sent → dedup → place order → persist + notify → SL/TP → tracking and exit.**

## 7. Monitoring and Recovery Flow

- **Observation:** atp-health-snapshot.timer runs on an interval (e.g. 5 min), runs verify.sh and GET /api/health/system, writes health state and system signals to log (e.g. /var/log/atp/health_snapshots.log). No remediation.
- **Notification:** atp-health-alert.timer runs on an interval (e.g. 5 min), evaluates streak-fail or other rules, may run remediate_market_data.sh, sends Telegram alerts with dedupe. No remediation (no service restarts).
- **Remediation:** atp-selfheal.timer runs on an interval (e.g. 2 min), runs verify.sh → heal.sh: disk cleanup, stack restart, POST /api/health/fix, nginx reload. This is the only canonical runtime remediation.
- **Infrastructure:** Host failure is handled by AWS EC2 status checks and auto-recovery, not by application timers.
- **Human:** Operators use runbooks to inspect, verify, and intervene when automated recovery is insufficient.

Signals (snapshots, health checks, logs) do not directly trigger actions; only the canonical remediation layer (atp-selfheal for runtime, AWS for host) performs recovery actions.

## 8. Operator Control Model

- **Inspection:** SSM, EC2 Instance Connect, or SSH; read logs (e.g. health_snapshots.log), run verify.sh, call /api/health and /api/health/system.
- **Verification:** Runbooks define verification commands and expected outputs; operators confirm health and data freshness before and after changes.
- **Intervention:** Runbooks for deployment, swap, recovery, observability, and incident response; operators execute steps manually when automation is not enough or when executing one-off procedures (e.g. consolidation, rollback).
- **Alerting:** Telegram alerts from atp-health-alert; operators react to notifications and follow runbooks.

Operators do not bypass the canonical recovery model; they supplement it with manual steps and runbook-driven actions.

## 9. Development Workflow Model

- **Motion:** Task prioritization, sequencing, deadlines, dependencies, ownership. Answers “What should be done next?”
- **OpenClaw:** Repository and architecture analysis, risk analysis, change planning, Cursor prompt generation. Answers “What exactly should change and how?”
- **Cursor:** Scoped code and documentation changes, script or infra changes only when approved. Answers “Apply the approved change safely.”

Tasks move: Motion task → OpenClaw analysis (findings, plan, Cursor prompt, verification, rollback) → Cursor implementation → verification → Motion updated and documentation updated. See **docs/OPERATING_MODEL_MOTION_OPENCLOW_CURSOR.md**.

## 10. Current Known Gaps

- **Repo vs PROD alignment:** Some repo-level scripts (health_monitor install, monitor_health.py cron, dashboard_health_check, nightly-integrity-audit) are not confirmed on PROD; overlap and retirement need verification per consolidation plan.
- **Observability coverage:** Observability baseline is defined but not every failure mode may have a dedicated signal or alert path; coverage of market data freshness, DB, and dependency health could be deepened.
- **Documentation of legacy paths:** Legacy or alternate health/alert paths in the repo are not fully inventoried and mapped to “canonical vs retire”; consolidation is one-mechanism-at-a-time and pending verification.
- **Unified architecture index:** Detailed flows (market data, trading, monitoring) live in multiple docs (signal_flow_overview, alert_to_order_flow, SYSTEM_MAP, runbooks); a single “architecture index” with clear pointers could reduce duplication and drift.
- **Runbook-to-baseline linkage:** Some runbooks may reference mechanisms or paths that are not part of the canonical baseline; periodic alignment of runbooks with the responsibility map and this master is recommended.

## 11. Recommended Next Architecture Priorities

**Roadmap:** Phase 1–3 (stability, recovery, observability) done; Phase 4 (mechanism inventory + verification) in progress; **Phase 5 = Market Data Flow Deep Dive** (scope: **docs/ARCHITECTURE_TASK_MARKET_DATA_FLOW_DEEP_DIVE.md**).

Ranked next architecture deep-dives:

1. **Consolidation verification and runbook alignment** — Confirm which repo mechanisms are actually present on PROD; update runbooks and the responsibility map so that “canonical” and “retired/optional” are explicit; one mechanism at a time per HEALTH_RECOVERY_CONSOLIDATION_PLAN.
2. **Market Data Flow Deep Dive** — Exchange → updater → validation → storage → consumers → health signals; single authoritative flow doc, freshness/staleness definition, failure-mode map (scope: docs/ARCHITECTURE_TASK_MARKET_DATA_FLOW_DEEP_DIVE.md).
3. **Operator control and observability playbooks** — Document operator decision points (when to rely on selfheal vs when to run a runbook), standard verification sequences, and how each observability signal (snapshot, alert, health API) maps to actions or runbooks.

---

**Related documents:**  
docs/ARCHITECTURE_TASK_MARKET_DATA_FLOW_DEEP_DIVE.md (Phase 5 scope) · docs/CANONICAL_MECHANISM_INVENTORY.md (operational truth source for mechanisms) · docs/PROD_INCIDENT_2026-03-11_RECOVERY.md · docs/PROD_MEMORY_HARDENING.md · docs/HEALTH_RECOVERY_CONSOLIDATION_PLAN.md · docs/CANONICAL_RECOVERY_RESPONSIBILITY_MAP.md · docs/OPERATING_MODEL_MOTION_OPENCLOW_CURSOR.md · docs/monitoring/signal_flow_overview.md · docs/monitoring/alert_to_order_flow.md · docs/SYSTEM_MAP.md
