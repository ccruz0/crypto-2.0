# Live Validation Runbook — Telegram and Execution Agents

**Version:** 1.0  
**Date:** 2026-03-15

Use this runbook to validate the Telegram and Alerts agent and the Execution and State agent with real tasks.

**First live run?** See [FIRST_LIVE_RUN_READINESS.md](FIRST_LIVE_RUN_READINESS.md) for selected tasks, exact steps, and [FIRST_LIVE_RUN_WORKSHEET.md](FIRST_LIVE_RUN_WORKSHEET.md) for recording results.

---

## 1. Prerequisite Checks

Run these before triggering tasks.

### 1.1 Backend and OpenClaw

```bash
# Backend health
curl -sS http://127.0.0.1:8002/ping_fast
# or for PROD: curl -sS https://dashboard.hilovivo.com/api/health

# OpenClaw reachable (from backend host)
curl -sS -H "Authorization: Bearer $OPENCLAW_API_TOKEN" \
  "${OPENCLAW_API_URL:-http://172.31.3.214:8080}/v1/responses" \
  -X POST -H "Content-Type: application/json" \
  -d '{"model":"openclaw","input":"ping"}' | head -c 200
```

**Pass:** Backend returns 200; OpenClaw returns JSON (not connection refused).

### 1.2 Agent Routing (no Notion)

```bash
cd backend
PYTHONPATH=. python scripts/validate_agent_routing.py
```

Or manually:

```bash
cd backend
PYTHONPATH=. python -c "
from app.services.agent_routing import route_task_with_reason
from app.services.agent_callbacks import select_default_callbacks_for_task

# Telegram
t = {'task': {'id': 'test-tg', 'task': 'Alerts not being sent', 'type': 'telegram', 'details': 'Test'}, 'repo_area': {}}
aid, reason = route_task_with_reason(t)
assert aid == 'telegram_alerts', (aid, reason)
pack = select_default_callbacks_for_task(t)
assert 'Telegram' in (pack.get('selection_reason') or '')
print('Telegram routing OK:', reason)

# Execution
t2 = {'task': {'id': 'test-ex', 'task': 'Order not in open orders', 'type': 'order', 'details': 'Test'}, 'repo_area': {}}
aid2, reason2 = route_task_with_reason(t2)
assert aid2 == 'execution_state', (aid2, reason2)
pack2 = select_default_callbacks_for_task(t2)
assert 'Execution' in (pack2.get('selection_reason') or '')
print('Execution routing OK:', reason2)
"
```

**Pass:** Both print "OK" with route reasons.

### 1.3 Notion and Telegram (for full flow)

- `NOTION_API_KEY` and `NOTION_TASK_DB` set
- Telegram approval flow configured (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, etc.)
- You can create a page in the Notion task DB and receive approval requests in Telegram

---

## 2. Trigger a Real Telegram/Alerts Task

### Option A: Notion + Scheduler (recommended)

1. **Create a Notion task** in the task database:
   - **Task (title):** `Alerts not being sent after deploy`
   - **Type:** `telegram` (or leave blank; keyword "alert" will match)
   - **Details:** `RUN_TELEGRAM is true but no messages reach Telegram. Check ENVIRONMENT and RUNTIME_ORIGIN.`
   - **Status:** `Planned`

2. **Run the scheduler:**
   ```bash
   ./scripts/run_notion_task_pickup.sh
   ```
   Or via Docker on PROD:
   ```bash
   docker compose --profile aws exec -e NOTION_TASK_DB="$NOTION_TASK_DB" backend-aws python -c "
   from app.services.agent_scheduler import run_agent_scheduler_cycle
   import json
   print(json.dumps(run_agent_scheduler_cycle(), default=str, indent=2))
   "
   ```

3. **Approve via Telegram** when the approval request arrives (agent tasks are `manual_only`).

4. **Check artifact:**
   ```bash
   ls -la docs/agents/telegram-alerts/notion-telegram-*.md
   ```

### Option B: Synthetic (no Notion)

For quick validation without Notion, run the apply callback directly:

```bash
cd backend
PYTHONPATH=. python -c "
from app.services.agent_callbacks import select_default_callbacks_for_task

task = {
    'task': {
        'id': 'validation-telegram-001',
        'task': 'Alerts not being sent after deploy',
        'type': 'telegram',
        'details': 'RUN_TELEGRAM true but no messages. Check ENVIRONMENT and RUNTIME_ORIGIN.',
    },
    'repo_area': {'area_name': 'telegram', 'likely_files': ['backend/app/services/telegram_notifier.py']},
}
pack = select_default_callbacks_for_task(task)
apply_fn = pack.get('apply_change_fn')
if apply_fn:
    r = apply_fn(task)
    print('Apply result:', r)
else:
    print('No apply fn:', pack.get('selection_reason'))
"
```

Use a unique ID per run (e.g. `validation-telegram-002`) to avoid overwriting.

---

## 3. Trigger a Real Execution/State Task

### Option A: Notion + Scheduler

1. **Create a Notion task:**
   - **Task:** `Order not in open orders - need to confirm EXECUTED vs CANCELED`
   - **Type:** `order`
   - **Details:** `User reports order missing from open orders. Exchange may show EXECUTED. Check order_history and lifecycle docs.`
   - **Status:** `Planned`

2. **Run scheduler** (same as §2).

3. **Approve via Telegram.**

4. **Check artifact:**
   ```bash
   ls -la docs/agents/execution-state/notion-execution-*.md
   ```

### Option B: Synthetic

```bash
cd backend
PYTHONPATH=. python -c "
from app.services.agent_callbacks import select_default_callbacks_for_task

task = {
    'task': {
        'id': 'validation-execution-001',
        'task': 'Order not in open orders',
        'type': 'order',
        'details': 'User reports order missing. Check order_history for EXECUTED vs CANCELED.',
    },
    'repo_area': {'area_name': 'execution', 'likely_files': ['backend/app/services/exchange_sync.py']},
}
pack = select_default_callbacks_for_task(task)
apply_fn = pack.get('apply_change_fn')
if apply_fn:
    r = apply_fn(task)
    print('Apply result:', r)
else:
    print('No apply fn:', pack.get('selection_reason'))
"
```

---

## 4. Logs to Inspect

| Log pattern | Meaning |
|-------------|---------|
| `agent_selected agent=telegram_alerts route_reason=...` | Telegram agent selected |
| `agent_selected agent=execution_state route_reason=...` | Execution agent selected |
| `agent_routing_init_failed` | Routing imports failed; fallback used |
| `openclaw_fallback reason=...` | OpenClaw not used; fallback or fail |
| `openclaw_apply_success task_id=...` | OpenClaw returned; note saved |
| `agent_output_validation: PASSED` | All 9 sections present; validation OK |
| `agent_output_validation: FAILED` | Missing sections or weak content |

**Where to look:** Backend stdout/stderr, Docker logs (`docker compose logs backend-aws`), or application log file.

---

## 5. Success Looks Like

- **Routing:** `agent_selected agent=telegram_alerts` or `agent_selected agent=execution_state` with explicit `route_reason`
- **Apply:** `openclaw_apply_success` with `sections=9` (or close)
- **Validation:** `agent_output_validation: PASSED`
- **Artifact:** `docs/agents/telegram-alerts/notion-telegram-{id}.md` or `docs/agents/execution-state/notion-execution-{id}.md` exists, ≥500 chars, all 9 sections present
- **Acceptance checklist:** All items pass (see [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md))

---

## 6. Failure Looks Like

| Symptom | Cause | Action |
|---------|-------|--------|
| `agent_routing_init_failed` | Import error (httpx, etc.) | Install deps; check backend env |
| `openclaw_fallback reason=not_configured` | No OPENCLAW_API_TOKEN | Set token and URL |
| `openclaw_fallback reason=openclaw_error` | OpenClaw returned error/empty | Check OpenClaw logs; retry |
| `agent_output_validation: FAILED — missing required sections` | Output incomplete | Re-run; check OpenClaw model |
| `agent_output_validation: FAILED — critical sections empty` | Root Cause / Proposed Fix too short | Re-run with clearer task details |
| Task routes to strategy-analysis instead of agent | Keyword conflict | Use Type=telegram or Type=order explicitly |

---

## 7. When to Rollback or Fall Back

- **Rollback:** Do not rollback agent framework. It is additive; failures only affect the specific task.
- **Fallback:** If agent routing fails, the task falls through to documentation, monitoring triage, or generic OpenClaw. The task still gets a callback; it may produce a different artifact (e.g. `docs/agents/generated-notes/`).
- **Manual override:** If validation fails repeatedly, a human can manually add missing sections to the note and re-run validation, or apply the fix directly via Cursor.

---

## 8. Example Real-World Test Tasks

See [REAL_WORLD_TEST_TASKS.md](REAL_WORLD_TEST_TASKS.md) for sanitized, implementation-based examples.
