# Anomaly Detection

Automated anomaly detection layer for the trading platform.
Creates Notion tasks when the system detects important operational or
trading-related inconsistencies.

## Scope

**Detection-only.** This module:

- Inspects existing local/project data
- Creates Notion tasks for discovered anomalies
- Logs structured activity events
- Optionally sends Telegram notifications

It does **not**:

- Modify trading execution or exchange sync
- Auto-fix any detected issue
- Change deployment, infrastructure, nginx, docker, or runtime config

Approval and execution of remediation still happens through the existing
agent workflow (scheduler → approval → execution).

## Detectors

### A. Open Order Mismatch

| Field | Value |
|-------|-------|
| Function | `detect_open_order_mismatch()` |
| Source data | `exchange_orders` DB table (active statuses) vs unified open-orders cache |
| Condition | Count of DB open orders ≠ count of cached open orders |
| Notion type | `monitoring` |
| Priority | Inferred by `notion_tasks` (keyword-based) |

### B. Signal Quality Degradation

| Field | Value |
|-------|-------|
| Function | `detect_signal_quality_degradation()` |
| Source data | `trade_signals` DB table (last 28 days baseline, last 7 days recent) |
| Condition | Recent fill/success rate drops ≥ 25% below baseline rate |
| Min sample | 5 signals in each period |
| Notion type | `strategy` |
| Priority | Inferred by `notion_tasks` |

### C. Scheduler Inactivity

| Field | Value |
|-------|-------|
| Function | `detect_scheduler_inactivity()` |
| Source data | Agent activity log (`logs/agent_activity.jsonl`) |
| Condition | No `scheduler_cycle_started` event within 15 minutes |
| Notion type | `monitoring` |
| Priority | Inferred by `notion_tasks` |

## Task Creation

Each detected anomaly creates a Notion task with:

| Property | Value |
|----------|-------|
| Task | `[Anomaly] <Name>` |
| Project | `Operations` |
| Type | Depends on detector (see above) |
| Priority | Inferred from title/details keywords |
| Source | `monitoring` |
| Status | `planned` |
| Details | Structured anomaly metadata |

Tasks are deduplicated by Notion's existing cooldown window
(`NOTION_TASK_COOLDOWN_SECONDS`, default 600s / 10 min).

## Activity Events

| Event | When |
|-------|------|
| `anomaly_detection_cycle_started` | Cycle begins |
| `anomaly_detected` | A detector finds an anomaly |
| `anomaly_task_created` | A Notion task is created for the anomaly |
| `anomaly_detection_cycle_completed` | Cycle ends (with summary counts) |

## Entry Point

```python
from app.services.agent_anomaly_detector import run_anomaly_detection_cycle

result = run_anomaly_detection_cycle()
# result = {
#     "ok": True,
#     "anomalies_found": 1,
#     "tasks_created": 1,
#     "anomalies": [...],
#     "tasks": [...],
#     "errors": [],
#     "completed_at": "2026-03-07T...",
# }
```

## Modules Reused

- `app.services.notion_tasks.create_notion_task` — task creation with dedup
- `app.services.agent_activity_log` — structured event logging
- `app.services.telegram_notifier.telegram_notifier` — safe Telegram sends
- `app.database.SessionLocal` — DB access for order/signal queries
- `app.services.open_orders_cache` — cached open-orders snapshot

## Intentionally Deferred

- Periodic background loop (can be added to `start_agent_scheduler_loop` or run independently)
- Additional detectors (balance drift, latency spikes, fill-rate anomalies)
- ML-based detection — current detectors use simple heuristics only
- API route to trigger detection on demand
