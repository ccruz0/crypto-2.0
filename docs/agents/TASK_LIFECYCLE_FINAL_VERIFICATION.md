# ATP Task Lifecycle — Final Verification Report

## 1. Direct Writes to needs-revision

**Result: ✓ No violations**

| Location | Type | Status |
|----------|------|--------|
| `agent_task_executor.py` | Uses `safe_transition_to_needs_revision()` | ✓ Approved path |
| `notion_tasks.py` | Guard rejects direct `update_notion_task_status(..., "needs-revision")` without metadata | ✓ Enforced |
| `test_task_status_transition.py` | Test calls direct update to verify rejection | ✓ Intentional |

**No remaining direct writes** outside the approved helper path.

---

## 2. Automatic Transitions — Required Fields

**Required:** from_status, to_status, reason, retryable, user_action_required

| Source | Event | from_status | to_status | reason | retryable | user_action_required |
|--------|-------|-------------|-----------|--------|-----------|----------------------|
| task_health_monitor (investigation stuck) | auto_transition | ✓ | ✓ | ✓ | ✓ | ✓ |
| task_health_monitor (max retries) | auto_transition | ✓ | ✓ | ✓ | ✓ | ✓ |
| task_status_transition | _log_transition | ✓ | ✓ | ✓ | ✓ | ✓ |
| needs_revision_processor (requeue) | auto_transition | ✓ | ✓ | ✓ | ✓ | ✓ |
| needs_revision_processor (blocked) | auto_transition | ✓ | ✓ | ✓ | ✓ | ✓ |

**Note:** Patching/testing stuck do not change status (same status + comment); no auto_transition required.

---

## 3. Telegram Messages — Structure

### Blocked (operational failure)
- ✓ Title, Status, Reason
- ✓ "No user revision required. Re-queue manually when ready."
- ✓ Re-investigate + View Report buttons
- ✓ Does NOT ask for user decision

### Needs Revision (verification failed)
- ✓ "Why it blocks progress:" — explicit
- ✓ "Feedback:" — verify_summary
- ✓ "Next step:" — Use Re-investigate to iterate
- ✓ Re-investigate + View Report buttons

---

## 4. Test Results

```
.venv/bin/python -m pytest backend/tests/test_task_health_monitor.py backend/tests/test_task_status_transition.py -v
```

**Result: 25 passed in 0.23s**

```
backend/tests/test_task_health_monitor.py::TestIsTaskStuck::* (8 passed)
backend/tests/test_task_health_monitor.py::TestHandleStuckTask::* (3 passed)
backend/tests/test_task_health_monitor.py::TestCheckForStuckTasks::* (3 passed)
backend/tests/test_task_status_transition.py::TestNeedsRevisionMetadata::* (6 passed)
backend/tests/test_task_status_transition.py::TestUpdateNotionTaskStatusNeedsRevisionGuard::* (2 passed)
backend/tests/test_task_status_transition.py::TestSafeTransitionToNeedsRevision::* (2 passed)
backend/tests/test_task_status_transition.py::TestTransitionTaskStatusInvalidNeedsRevision::* (1 passed)
```

---

## 5. Deployment Checklist

### LAB (i-0d82c172235770a0d)
```bash
# 1. Ensure main has the lifecycle hardening commit
git fetch origin main && git log -1 --oneline origin/main

# 2. Deploy via SSM (git pull + rebuild + restart)
LAB_INSTANCE_ID=i-0d82c172235770a0d ./scripts/aws/deploy_notion_runtime_to_lab_and_verify.sh
# Or manual: aws ssm send-command --instance-ids i-0d82c172235770a0d ... (git pull, docker compose build, restart)

# 3. Verify task pickup
./scripts/run_notion_task_pickup.sh
```

### PROD (i-087953603011543c5)
```bash
# 1. Ensure main is pushed
git push origin main

# 2. Deploy via SSM
./scripts/deploy_production_via_ssm.sh

# 3. Verify health
curl -s -o /dev/null -w '%{http_code}' https://dashboard.hilovivo.com/api/health
```

### Other runtimes (e.g. local, cron)
- Pull latest code
- Restart backend container / process
- Ensure `task_status_transition.py` and `needs_revision_processor.py` are present

---

## 6. Commands for Future Validation

### Run lifecycle tests
```bash
cd /Users/carloscruz/automated-trading-platform
.venv/bin/python -m pytest backend/tests/test_task_health_monitor.py backend/tests/test_task_status_transition.py -v
```

### Grep for violations (direct needs-revision writes)
```bash
# Should return ONLY: agent_task_executor (safe_transition), notion_tasks (guard), tests
rg -n 'update_notion_task_status.*needs|TASK_STATUS_NEEDS_REVISION' backend/app --type py

# Exclude docs/tests: any direct status="needs-revision" outside task_status_transition
rg -n '"needs-revision"|'\''needs-revision'\''|update_notion_task_status\s*\([^)]*needs' backend/app/services --type py
```

### Grep for bypass (should use safe_transition or transition_task_status)
```bash
# Callers of update_notion_task_status with needs-revision must pass needs_revision_metadata
rg -n 'update_notion_task_status\s*\(' backend/app/services --type py -A 2
```

---

## 7. Go/No-Go Recommendation

**GO**

- No direct writes to needs-revision outside approved path
- All automatic transitions emit required fields
- Telegram messages are structurally correct and actionable
- 25/25 tests pass
- Invariant enforced at notion_tasks layer
