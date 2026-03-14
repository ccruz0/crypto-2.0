# Architecture Task: Market Data Flow Deep Dive

**Status:** Next (Phase 5) — after mechanism verification (Phase 4)  
**Type:** Architecture analysis and documentation only. No runtime changes.

---

## 1. Purpose

This document defines the **Market Data Flow Deep Dive** as the next architecture task once mechanism verification (nightly-integrity-audit, dashboard_health_check) is complete. Alerts such as **market_updater stale** are upstream of signals, orders, and execution; understanding and documenting the full market data path is where the next reliability improvements will come from.

The deep-dive produces **analysis and documentation** only. Implementation or hardening changes follow the Motion / OpenClaw / Cursor workflow and are out of scope for this task definition.

## 2. Place in the Roadmap

| Phase | Name | Status |
|-------|------|--------|
| 1 | Production stability (EC2, swap, docker, nginx, ATP services) | ✓ done |
| 2 | Recovery architecture (AWS, atp-selfheal, alerts, snapshot) | ✓ done |
| 3 | Observability baseline | ✓ done |
| 4 | Mechanism inventory + verification | → in progress |
| **5** | **Market data architecture deep dive** | **→ next** |
| 6 | Trading execution architecture | → later |

## 3. Scope of the Deep Dive

Analyze and document the end-to-end path:

1. **Exchange** — Where market data originates (Crypto.com, Binance, etc.); API contracts, rate limits, failure modes.
2. **Updater** — How the market updater runs (process, container, schedule); how it is started, restarted, and how “stale” is detected.
3. **Validation** — How freshness is verified (timestamps, health checks, observability signals); what “stale” means and who decides it.
4. **Storage** — Where data is persisted (MarketData, MarketPrice, SQLite/PostgreSQL); retention, consistency, and fallbacks.
5. **Consumers** — Who reads market data (SignalMonitorService, routes_market, dashboard, health/alert pipeline); dependencies and failure impact.
6. **Health signals** — How market data health is exposed (e.g. verify.sh, atp-health-snapshot, atp-health-alert, remediate_market_data.sh); how “market_updater stale” is raised and remediated.

## 4. Key Questions to Answer

- Where does market data originate, and what happens when an exchange is unreachable?
- How is the updater process/container started and restarted (manual, Docker, atp-selfheal, remediate_market_data)?
- How is freshness validated, and what is the exact definition of “stale” in the code and in alerts?
- What are the fallback sources (e.g. MarketPrice vs MarketData, price_fetcher) and in what order are they used?
- What data validity or consistency guarantees exist (e.g. max age, required fields) before data is used for signals or display?
- How does “market_updater stale” propagate into alerts and remediation, and is that path documented and single-threaded?

## 5. Deliverables (Expected Outputs)

- **Market data flow document** — Single authoritative description: exchange → updater → validation → storage → consumers → health signals, with repo paths and ownership.
- **Freshness and staleness definition** — Clear specification of how “stale” is defined, where it is checked, and how it triggers alerts or remediation.
- **Failure mode map** — What happens when: updater dies, exchange is down, DB is unavailable, consumer reads old data; and which component (if any) recovers each case.
- **Gap and hardening options** — Documented list of architectural gaps and optional hardening measures (no implementation in this task; implementation is a later, approved change).

## 6. Relationship to Existing Docs

- **docs/SOLUTION_ARCHITECTURE_MASTER.md** — Section 5 (Market Data Flow) gives a high-level summary; this deep-dive expands it into the single source of truth for the market data path.
- **docs/monitoring/signal_flow_overview.md** — Covers data sources and signal calculation; the deep-dive should align with it and extend it with updater lifecycle, validation, and health signals.
- **docs/CANONICAL_RECOVERY_RESPONSIBILITY_MAP.md** — Remediation (e.g. remediate_market_data.sh invoked by atp-health-alert) is one consumer of “market data unhealthy”; the deep-dive should make the link explicit.
- **docs/runbooks/EC2_FIX_MARKET_DATA_NOW.md** — Operator runbook for fixing market data; deep-dive should reference it and ensure the documented flow matches runbook assumptions.

## 7. Out of Scope for This Task

- **No runtime or code changes** — This task is analysis and documentation only. Any hardening or implementation follows the operating model (Motion → OpenClaw → Cursor) and separate approval.
- **No new mechanisms** — The deep-dive documents current behavior; it does not authorize new timers, scripts, or services.
- **Trading execution flow** — In scope only insofar as “where do signals get their market data”; full order/execution flow is Phase 6.

## 8. Prerequisite

Complete **Phase 4** verification (nightly-integrity-audit and dashboard_health_check) and update **docs/CANONICAL_MECHANISM_INVENTORY.md** so that mechanism status is no longer “Unknown” for those two. Then treat this document as the scope for the Market Data Flow Deep Dive (e.g. as an OpenClaw/Cursor analysis task).

---

**Discipline:** Verification before change. This task defines *what* to analyze; it does not change how the platform runs until findings are turned into approved changes.
