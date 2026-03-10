# Agent Ops Tab – UI vs Backend Validation

This document maps the Agent Ops tab UI to the backend API responses to ensure they match exactly.

## Endpoints and UI Mapping

| Endpoint | UI Section | Fields Used |
|----------|------------|-------------|
| `GET /api/agent/status` | Scheduler | All fields |
| `GET /api/agent/ops/active-tasks` | Active tasks tables | patching, deploying, awaiting_deploy_approval |
| `GET /api/agent/ops/recovery` | Recent recovery actions | recovery_actions |
| `GET /api/agent/ops/smoke-checks` | Recent smoke checks | smoke_checks |
| `GET /api/agent/ops/failed-investigations` | Failed investigations | failed_investigations |
| `GET /api/agent/ops/deploy-tracker` | Recent deploys | recent_deploys, last_deploy_task_id |

## Field-by-Field Mapping

### 1. `/api/agent/status`

| Backend Field | UI Display | Notes |
|---------------|------------|-------|
| `scheduler_running` | Running (Yes/No) | ✓ |
| `automation_enabled` | Automation (Enabled/Disabled) | ✓ |
| `last_scheduler_cycle` | Last cycle | ✓ Empty → "—" |
| `scheduler_interval_s` | Interval (s) | ✓ |
| `pending_approvals` | Pending approvals | ✓ -1 → "—" |
| `pending_notion_tasks` | Planned: N | ✓ |
| `tasks_in_investigation` | Investigation: N | ✓ |
| `tasks_in_patch_phase` | Patching: N | ✓ |
| `tasks_awaiting_deploy` | Awaiting deploy: N | ✓ |
| `tasks_deploying` | Deploying: N | ✓ |

### 2. `/api/agent/ops/active-tasks`

| Backend Field | UI Display | Notes |
|---------------|------------|-------|
| `ok` | Show/hide section | Only render when ok=true |
| `patching` | Patching table | Columns: task, status, priority |
| `deploying` | Deploying table | Same structure |
| `awaiting_deploy_approval` | Awaiting deploy approval table | Same structure |

Task item fields: `id`, `task`, `status`, `priority` (all optional in UI).

### 3. `/api/agent/ops/recovery`

| Backend Field | UI Display | Notes |
|---------------|------------|-------|
| `ok` | Error banner if false | "Some data may be unavailable" |
| `recovery_actions` | Event list | timestamp, event_type, task_title/task_id, details.outcome |

### 4. `/api/agent/ops/smoke-checks`

| Backend Field | UI Display | Notes |
|---------------|------------|-------|
| `ok` | Error banner if false | Same as recovery |
| `smoke_checks` | Event list | timestamp, event_type, task_title/task_id, details.outcome (green/amber) |

### 5. `/api/agent/ops/failed-investigations`

| Backend Field | UI Display | Notes |
|---------------|------------|-------|
| `ok` | Error banner if false | Same |
| `failed_investigations` | Event list | timestamp, event_type, task_title/task_id, details.summary |

### 6. `/api/agent/ops/deploy-tracker`

| Backend Field | UI Display | Notes |
|---------------|------------|-------|
| `ok` | Error banner if false; show "No recent deploys" when empty | ✓ |
| `recent_deploys` | List items | task_id, triggered_at, triggered_by |
| `last_deploy_task_id` | Footer line | Only when non-empty |

## Validation Script

Run the validation script to verify backend responses:

```bash
# Local backend (port 8002)
./scripts/validate_agent_ops_tab.sh

# Production
BASE_URL=https://dashboard.hilovivo.com/api ./scripts/validate_agent_ops_tab.sh
```

The script checks that all expected keys exist in each response.

## Polling and Limits

| API | Limit Used | Poll Interval |
|-----|------------|---------------|
| status | — | 45s |
| recovery | 15 | 45s |
| failed-investigations | 15 | 45s |
| active-tasks | — | 45s |
| smoke-checks | 15 | 45s |
| deploy-tracker | 8 | 45s |

## Visual Improvements (Operational Readability)

- **Status badges**: Scheduler (Running/Stopped), Automation (Enabled/Disabled), smoke check outcomes (passed/failed), recovery outcomes, failed investigation event types.
- **Table badges**: Patching (amber), Deploying (green), Awaiting deploy approval (gray) with count badges.
- **Stale highlighting**: Active tasks with no event in 15 min (patching/awaiting) or 10 min (deploying) show amber left border and background. Uses last event timestamp from recovery, smoke checks, failed investigations, and deploy tracker.
