# Real-World Test Tasks — Telegram and Execution Agents

**Version:** 1.0  
**Date:** 2026-03-15

Sanitized, implementation-based example tasks for live validation. Use these in Notion or synthetic runs.

---

## Telegram and Alerts Agent

### Task 1: Alerts not sent (ENVIRONMENT / RUNTIME_ORIGIN)

**Source:** [docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md](../../runbooks/TELEGRAM_ALERTS_NOT_SENT.md) — origin block, env mismatch.

| Field | Value |
|-------|-------|
| **Task (title)** | Alerts not being sent after deploy |
| **Type** | `telegram` |
| **Details** | RUN_TELEGRAM is true but no messages reach Telegram. Signal monitor runs on LAB with ENVIRONMENT=staging. alert_emitter may block sends when origin != AWS. Check RUNTIME_ORIGIN and docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md. |
| **Expected route** | `telegram_alerts` (task_type:telegram or keyword:alert) |
| **Expected scope** | telegram_notifier.py, alert_emitter.py, TELEGRAM_ALERTS_NOT_SENT.md |
| **Expected root cause** | ENVIRONMENT or RUNTIME_ORIGIN blocks sends; only AWS origin sends |

---

### Task 2: Throttle / repeated alerts

**Source:** signal_throttle.py, throttle logic.

| Field | Value |
|-------|-------|
| **Task (title)** | Repeated alerts for same trade |
| **Type** | (blank or `bug`) |
| **Details** | User gets duplicate Telegram alerts for a single order execution. Check signal_throttle.py and alert_emitter dedup logic. Throttle cooldown may be too short or bypassed. |
| **Expected route** | `telegram_alerts` (keyword:repeated alerts or keyword:alert) |
| **Expected scope** | signal_throttle.py, alert_emitter.py |
| **Expected root cause** | Throttle window, dedup key, or cooldown misconfiguration |

---

## Execution and State Agent

### Task 1: Order not in open orders

**Source:** [docs/ORDER_LIFECYCLE_GUIDE.md](../../ORDER_LIFECYCLE_GUIDE.md) — "Order not in open orders does NOT mean canceled".

| Field | Value |
|-------|-------|
| **Task (title)** | Order not in open orders - confirm EXECUTED vs CANCELED |
| **Type** | `order` |
| **Details** | User reports order missing from open orders. Dashboard shows PENDING. Must NOT assume canceled. Check exchange_sync order_history and trade_history; docs/ORDER_LIFECYCLE_GUIDE.md. |
| **Expected route** | `execution_state` (task_type:order or keyword:order) |
| **Expected scope** | exchange_sync.py, signal_monitor.py, crypto_com_trade.py, ORDER_LIFECYCLE_GUIDE.md |
| **Expected root cause** | Order filled (EXECUTED); open_orders excludes filled; DB/dashboard lag sync |

---

### Task 2: Dashboard vs exchange mismatch

**Source:** exchange_order model, dashboard state rendering.

| Field | Value |
|-------|-------|
| **Task (title)** | Dashboard showing wrong order state |
| **Type** | (blank or `bug`) |
| **Details** | Dashboard shows order as PENDING but exchange API order_history shows EXECUTED. State reconciliation or lifecycle event ordering issue. Check exchange_sync, exchange_order model, and dashboard data source. |
| **Expected route** | `execution_state` (keyword:dashboard mismatch or keyword:order) |
| **Expected scope** | exchange_sync.py, exchange_order model, dashboard API |
| **Expected root cause** | Sync lag, lifecycle event ordering, or dashboard cache |

---

## How to Use

1. **Notion:** Create a page in the task DB with the fields above. Set Status = Planned. Run scheduler.
2. **Synthetic:** Use the task dict in the [LIVE_VALIDATION_RUNBOOK](LIVE_VALIDATION_RUNBOOK.md) §2 Option B / §3 Option B, substituting the task fields.
