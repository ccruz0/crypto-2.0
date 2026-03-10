# Agent Operations Visibility Layer

Lightweight read-only API for observing autonomous recovery and orchestration flow without relying only on raw logs.

## Data Sources (Current)

| Source | Location | Content |
|--------|----------|---------|
| `/api/agent/status` | routes_agent.py | Scheduler state, task counts by lifecycle stage |
| `agent_activity.jsonl` | logs/agent_activity.jsonl | Structured events (JSONL) |
| Notion task statuses | notion_task_reader | Tasks by status |
| Deploy tracker | deploy_trigger._recent_deploys | In-process recent deploys |
| Recovery events | agent_activity (event_type filter) | recovery_*_attempt |

## New Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/agent/ops/recovery` | GET | Recent autonomous recovery actions |
| `/api/agent/ops/failed-investigations` | GET | Recent execution_failed, validation_failed |
| `/api/agent/ops/active-tasks` | GET | Tasks in patching, deploying, awaiting-deploy-approval |
| `/api/agent/ops/smoke-checks` | GET | Last smoke check outcomes |
| `/api/agent/ops/deploy-tracker` | GET | Recent deploy dispatches |

### Query Parameters

- `limit` (int, 1–100): Max events to return for recovery, failed-investigations, smoke-checks. Default 20.
- `limit` (int, 1–50): Max deploy entries for deploy-tracker. Default 10.

## Example JSON Responses

### GET /api/agent/ops/recovery?limit=5

```json
{
  "ok": true,
  "recovery_actions": [
    {
      "timestamp": "2025-03-08T14:30:00.123Z",
      "event_type": "recovery_orphan_smoke_attempt",
      "task_id": "abc123-def456-...",
      "task_title": "Fix health endpoint",
      "details": {
        "outcome": "passed",
        "advanced": true,
        "blocked": false,
        "summary": "Smoke check PASSED: 2 checks OK (450ms)"
      }
    }
  ],
  "count": 1
}
```

### GET /api/agent/ops/failed-investigations?limit=5

```json
{
  "ok": true,
  "failed_investigations": [
    {
      "timestamp": "2025-03-08T12:00:00.000Z",
      "event_type": "validation_failed",
      "task_id": "xyz789-...",
      "task_title": "Fix API timeout",
      "details": {
        "summary": "investigation note missing concrete module references"
      }
    }
  ],
  "count": 1
}
```

### GET /api/agent/ops/active-tasks

```json
{
  "ok": true,
  "patching": [
    {
      "id": "abc123-...",
      "task": "Fix health endpoint",
      "status": "patching",
      "priority": "high"
    }
  ],
  "deploying": [],
  "awaiting_deploy_approval": [
    {
      "id": "def456-...",
      "task": "Update monitoring docs",
      "status": "awaiting-deploy-approval",
      "priority": "medium"
    }
  ]
}
```

### GET /api/agent/ops/smoke-checks?limit=5

```json
{
  "ok": true,
  "smoke_checks": [
    {
      "timestamp": "2025-03-08T14:30:00.123Z",
      "event_type": "smoke_check_recorded",
      "task_id": "abc123-...",
      "task_title": "Fix health endpoint",
      "details": {
        "outcome": "passed",
        "summary": "Smoke check PASSED: 2 checks OK (450ms)",
        "advanced": true,
        "advanced_to": "done"
      }
    }
  ],
  "count": 1
}
```

### GET /api/agent/ops/deploy-tracker?limit=5

```json
{
  "ok": true,
  "recent_deploys": [
    {
      "task_id": "abc123-...",
      "triggered_at": "2025-03-08T14:25:00.000Z",
      "triggered_by": "telegram_user"
    }
  ],
  "last_deploy_task_id": "abc123-..."
}
```

## Dashboard Tab (Implemented)

The **Agent Ops** tab is available in the main dashboard. It displays:

- Scheduler state (running, automation enabled, last cycle, pending approvals)
- Task counts by lifecycle stage
- Active tasks: patching, deploying, awaiting-deploy-approval
- Recent recovery actions
- Recent smoke checks
- Failed investigations
- Recent deploy dispatches

Polling: every 45 seconds. Manual refresh button available.

---

## Notes for Future Enhancements

### Suggested Layout

1. **Header row**
   - Status summary from `/api/agent/status` (scheduler running, automation enabled, counts)
   - Last cycle timestamp

2. **Active tasks**
   - Table: `patching` | `deploying` | `awaiting_deploy_approval`
   - Columns: task title, status, priority, Notion link (id)
   - Source: `/api/agent/ops/active-tasks`

3. **Recent recovery**
   - List of recovery events with outcome
   - Source: `/api/agent/ops/recovery`
   - Color: green (passed/regenerated), red (failed/reset), gray (error)

4. **Recent smoke checks**
   - List of smoke check outcomes
   - Source: `/api/agent/ops/smoke-checks`
   - Show outcome, task_id, advanced/blocked

5. **Failed investigations**
   - List of execution_failed, validation_failed
   - Source: `/api/agent/ops/failed-investigations`
   - Useful for triage

6. **Deploy tracker**
   - Last deploy task_id, recent deploys
   - Source: `/api/agent/ops/deploy-tracker`
   - Useful for webhook correlation debugging

### Polling / Refresh

- Poll `/api/agent/status` every 60s for summary
- Poll `/api/agent/ops/*` every 30–60s for detail tables
- Or use a single "Refresh" button to avoid constant polling

### Implementation Notes

- Backend-only for now; no frontend changes required
- All endpoints are read-only; no auth required beyond existing API auth
- Activity log is JSONL; events are read in reverse order (newest first)
- Deploy tracker is in-process; resets on backend restart
