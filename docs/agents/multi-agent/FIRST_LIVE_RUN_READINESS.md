# First Live Run Readiness — Telegram and Execution Agents

**Version:** 1.0  
**Date:** 2026-03-15

---

## Readiness Assessment

| Check | Status |
|-------|--------|
| Routing validation passed | ✅ OK |
| Runbook, checklist, test tasks documented | ✅ OK |
| Synthetic trigger path (no Notion) available | ✅ OK |
| Full flow path (Notion + scheduler + approval) documented | ✅ OK |
| OpenClaw must be configured for apply | ⚠️ Required |
| Backend must be running for full flow | ⚠️ Required |

**Verdict:** Ready for first live runs. Recommend **synthetic runs first** (fewer dependencies), then full flow.

---

## First Live Test Selection

### Telegram and Alerts Agent — Selected: Task 1 (Alerts not sent)

**Why this is the best first live validation:**

1. **Explicit routing:** `Type=telegram` guarantees `task_type:telegram` match; no keyword ambiguity.
2. **Documented source:** [TELEGRAM_ALERTS_NOT_SENT.md](../../runbooks/TELEGRAM_ALERTS_NOT_SENT.md) describes the real issue; agent has clear reference.
3. **Narrow scope:** ENVIRONMENT / RUNTIME_ORIGIN block; agent prompt already lists these.
4. **Low risk:** Analysis only; no production changes.
5. **Easy to verify:** Output should cite `telegram_notifier`, `alert_emitter`, and runbook.

---

### Execution and State Agent — Selected: Task 1 (Order not in open orders)

**Why this is the best first live validation:**

1. **Explicit routing:** `Type=order` guarantees `task_type:order` match.
2. **Canonical case:** [ORDER_LIFECYCLE_GUIDE.md](../../ORDER_LIFECYCLE_GUIDE.md) explicitly states "Order not in open orders does NOT mean canceled"; agent prompt reinforces this.
3. **Agent-specific:** Execution agent is designed for this; prompt includes the critical warning.
4. **Low risk:** Analysis only; no order placement changes.
5. **Easy to verify:** Output should cite `exchange_sync`, `order_history`, and lifecycle docs.

---

## Operator Steps (Synthetic — Recommended First)

### Prerequisites (exact)

- [ ] `cd backend && PYTHONPATH=. python scripts/validate_agent_routing.py` → All checks passed
- [ ] Backend reachable: `curl -sS http://127.0.0.1:8002/ping_fast` → 200 (or PROD URL)
- [ ] `OPENCLAW_API_TOKEN` and `OPENCLAW_API_URL` set in env (or backend `.env` / `secrets/runtime.env`)
- [ ] OpenClaw reachable from backend host (see runbook §1.1)

### Trigger: Telegram Agent

```bash
cd backend
PYTHONPATH=. python -c "
from app.services.agent_callbacks import select_default_callbacks_for_task

task = {
    'task': {
        'id': 'live-tg-001',
        'task': 'Alerts not being sent after deploy',
        'type': 'telegram',
        'details': 'RUN_TELEGRAM is true but no messages reach Telegram. Signal monitor runs on LAB with ENVIRONMENT=staging. alert_emitter may block sends when origin != AWS. Check RUNTIME_ORIGIN and docs/runbooks/TELEGRAM_ALERTS_NOT_SENT.md.',
    },
    'repo_area': {'area_name': 'telegram', 'likely_files': ['backend/app/services/telegram_notifier.py', 'backend/app/services/alert_emitter.py']},
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

### Trigger: Execution Agent

```bash
cd backend
PYTHONPATH=. python -c "
from app.services.agent_callbacks import select_default_callbacks_for_task

task = {
    'task': {
        'id': 'live-ex-001',
        'task': 'Order not in open orders - confirm EXECUTED vs CANCELED',
        'type': 'order',
        'details': 'User reports order missing from open orders. Dashboard shows PENDING. Must NOT assume canceled. Check exchange_sync order_history and trade_history; docs/ORDER_LIFECYCLE_GUIDE.md.',
    },
    'repo_area': {'area_name': 'execution', 'likely_files': ['backend/app/services/exchange_sync.py', 'backend/app/services/signal_monitor.py']},
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

## Logs to Check (exact patterns)

| Agent | Pattern | Meaning |
|-------|---------|---------|
| Telegram | `agent_selected agent=telegram_alerts route_reason=task_type:telegram` | Correct routing |
| Telegram | `openclaw_apply_success task_id=live-tg-001` | Apply succeeded |
| Telegram | `agent_output_validation: PASSED task_id=live-tg-001` | Validation passed |
| Execution | `agent_selected agent=execution_state route_reason=task_type:order` | Correct routing |
| Execution | `openclaw_apply_success task_id=live-ex-001` | Apply succeeded |
| Execution | `agent_output_validation: PASSED task_id=live-ex-001` | Validation passed |
| Either | `openclaw_fallback reason=...` | OpenClaw not used; note reason |
| Either | `agent_routing_init_failed` | Routing failed; fallback used |

---

## Pass/Fail Criteria

### Pass

- `apply_fn` ran and returned `{"success": True, ...}`
- Artifact exists: `docs/agents/telegram-alerts/notion-telegram-live-tg-001.md` or `docs/agents/execution-state/notion-execution-live-ex-001.md`
- Logs show `agent_selected`, `openclaw_apply_success`, `agent_output_validation: PASSED`
- [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) items 1–5 pass for that agent

### Fail

- `apply_fn` is None → routing/callback selection failed
- `{"success": False, "summary": "..."}` → OpenClaw or validation failed
- `openclaw_fallback` without expected artifact → OpenClaw not configured or error
- `agent_output_validation: FAILED` → output incomplete; check summary for missing sections

---

## Evidence to Capture

1. **Apply result:** stdout from the Python `print('Apply result:', r)` (or screenshot)
2. **Log excerpt:** grep for `agent_selected`, `openclaw_apply_success`, `agent_output_validation` (or equivalent)
3. **Artifact path:** `ls -la docs/agents/telegram-alerts/notion-telegram-live-tg-001.md` and `docs/agents/execution-state/notion-execution-live-ex-001.md`
4. **Artifact size:** `wc -c` on the artifact file (body after `---` should be ≥500 chars)
5. **Acceptance checklist:** completed [ACCEPTANCE_CHECKLIST.md](ACCEPTANCE_CHECKLIST.md) for the run

---

## Tiny Improvements (Optional)

| Item | Why | Effort |
|------|-----|--------|
| Add `scripts/run_agent_synthetic_apply.sh` | Single command for synthetic apply; avoids copy-paste | Low |
| Log task_id in apply result | Easier to grep logs when ID is dynamic | Trivial |
| Document OpenClaw health endpoint | Runbook §1.1 uses `/v1/responses`; some gateways may have `/health` | Trivial |

None of these block the first live run. Implement only if operator feedback suggests they are needed.
