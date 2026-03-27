# Production Orchestration Debugging Guide

> **EC2 host**: `52.220.32.147` (`dashboard.hilovivo.com`)
> **SSH**: `ssh -i ~/.ssh/atp-rebuild-2026.pem ubuntu@52.220.32.147`
> **Working dir**: `~/crypto-2.0`
> **All commands below assume you are SSH'd in and inside that directory.**

---

## First Command to Run

```bash
cd /home/ubuntu/crypto-2.0
docker compose --profile aws logs --tail=500 -f backend-aws
```

This streams the last 500 lines and follows new output. Every orchestration log flows through the `backend-aws` container's stdout.

---

## Golden Path — Healthy Extended Lifecycle

A bug-type task that completes without errors follows this sequence:

```
planned
  → investigation-complete      (OpenClaw analysis saved, Telegram approval sent)
  → ready-for-patch             (operator approves investigation via Telegram)
  → patching                    (validation runs, test gate writes Test Status)
  → awaiting-deploy-approval    (test gate passed, Telegram deploy approval sent)
  → deploying                   (operator approves deploy via Telegram)
  → done                        (smoke check passed)
```

Legacy (non-bug) tasks follow the shorter path:

```
Legacy path: in-progress → testing → deployed (canonical path uses investigation/patch/deploy/smoke gates)
```

The lifecycle is determined by `manual_only` in callback selection. If `manual_only=True`, the extended lifecycle is used.

---

## Where Logs Live

| Source | Location | Retention |
|---|---|---|
| Container stdout/stderr | Docker json-file driver (default) | Until container is removed |
| JSONL activity log | `/app/logs/agent_activity.jsonl` inside container (not volume-mounted) | Lifetime of container filesystem |
| GitHub Actions | [github.com/ccruz0/crypto-2.0/actions](https://github.com/ccruz0/crypto-2.0/actions) | 90 days (GitHub default) |

---

## Stage-by-Stage Reference

### 1. Scheduler Cycle

The scheduler loop picks up Notion tasks, retries approved failures, and continues `ready-for-patch` tasks.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "scheduler_cycle_start|scheduler_no_task|agent_scheduler_cycle_done|scheduler_retry_done|scheduler_patch_continuation_done"
```

| Signal | Keyword |
|---|---|
| Cycle started | `scheduler_cycle_start` |
| No pending tasks | `scheduler_no_task: prepare_task_with_approval_check returned None` |
| Cycle done | `agent_scheduler_cycle_done ok=True` |
| Retry cycle done | `scheduler_retry_done` |
| Patch continuation done | `scheduler_patch_continuation_done` |
| Cycle error | `agent_scheduler_loop: cycle raised` |
| Anomaly scan done | `anomaly_detection_cycle_done` |

---

### 2. Notion Task Parsing

Reading tasks from Notion and parsing the `Type` field.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "notion_scan_started|task_detected|notion_tasks_found|_parse_page.*Type field"
```

| Signal | Keyword |
|---|---|
| Scan started | `notion_scan_started` |
| Task found | `task_detected` |
| Task count | `notion_tasks_found` |
| Type parsed | `_parse_page: Type field — notion_prop_type=` |
| API key missing | `Notion task reader skipped: NOTION_API_KEY not set` |
| Query failed | `Notion query returned status=` |
| All filters failed | `Notion task read failed: all filter combinations` |

---

### 3. Callback Selection

Determines which callback pack (bug_investigation, documentation, generic, etc.) and whether `manual_only=True`.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "select_default_callbacks_for_task"
```

| Signal | Keyword |
|---|---|
| Type detected | `select_default_callbacks_for_task: task_type_raw=` |
| Bug explicit match | `explicit bug type detected — selecting bug_investigation pack` |
| Bug keyword match | `matched bug_investigation via keyword heuristics` |
| Generic fallback | `no specific match, using generic OpenClaw` |
| No match at all | `NO callback matched — returning None` |

---

### 4. Lifecycle Decision

The executor decides between extended lifecycle (`manual_only=True`) and legacy lifecycle.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "LIFECYCLE DECISION|LIFECYCLE BRANCH"
```

| Signal | Keyword |
|---|---|
| Decision made | `LIFECYCLE DECISION task_id=... task_type=... manual_only=... _use_extended_lifecycle=...` |
| Branch taken | `LIFECYCLE BRANCH task_id=... use_extended_lifecycle=...` |

---

### 5. Bundle Deserialization (Telegram Re-execution)

When a task is approved via Telegram, the stored bundle is deserialized and callbacks are re-selected with a fresh Notion type read.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "CALLBACK RE-SELECTION|refreshed task type|type is empty|type unchanged|type refresh failed"
```

| Signal | Keyword |
|---|---|
| Type refreshed from Notion | `refreshed task type from Notion task_id=... stored_type=... fresh_type=...` |
| Type empty in Notion | `Notion type is empty, keeping stored` |
| Type unchanged | `task type unchanged` |
| Refresh failed | `Notion type refresh failed` |
| Re-selection result | `CALLBACK RE-SELECTION task_id=... manual_only=... selection_reason=...` |
| Re-selection error | `callback re-selection FAILED` |

---

### 6. Telegram Approval Handling

User approves/rejects tasks via Telegram inline buttons.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "\[TG\]\[APPROVAL\]|\[TG\]\[EXT_APPROVAL\]"
```

| Signal | Keyword |
|---|---|
| Callback routed | `[TG][APPROVAL] Routing callback_data=` |
| Task approved (legacy) | `[TG][APPROVAL] Approved task_id=... starting execution` |
| Task denied (legacy) | `[TG][APPROVAL] Denied task_id=` |
| Extended callback routed | `[TG][EXT_APPROVAL] Routing callback_data=` |
| Patch approved | `[TG][EXT_APPROVAL] task ... → ready-for-patch` |
| Deploy approved | `[TG][EXT_APPROVAL] task ... → deploying` |
| Deploy blocked by gate | `[TG][EXT_APPROVAL] deploy blocked by test gate` |
| Task rejected | `[TG][EXT_APPROVAL] task ... → rejected` |
| Smoke check result | `[TG][EXT_APPROVAL] smoke check completed` |
| Error | `[TG][APPROVAL] Error handling` or `[TG][EXT_APPROVAL] Error handling` |

---

### 7. OpenClaw Execution

External AI analysis call for investigations, reports, etc.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "openclaw_client:|OpenClaw"
```

| Signal | Keyword |
|---|---|
| Request sent | `openclaw_client: sending request` |
| Response OK | `openclaw_client: response received` |
| Non-200 | `openclaw_client: non-200 response` |
| Timeout | `openclaw_client: timeout after` |
| Connection failed | `openclaw_client: connection failed` |
| Not configured | `OpenClaw not configured — using template fallback` |
| Call failed | `OpenClaw call failed for task` |
| Analysis saved | `OpenClaw analysis saved for task` |
| Sections sidecar saved | `Structured sections sidecar saved at` |

---

### 8. Cursor Handoff

Saving structured output as section sidecars for downstream use.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "Cursor handoff|cursor_handoff"
```

| Signal | Keyword |
|---|---|
| Generated | `Cursor handoff generated task_id=` |
| Saved | `Cursor handoff saved` |
| Generation failed | `_generate_cursor_handoff failed` |
| Save failed | `save_cursor_handoff failed` |

---

### 9. Test Gate / Deploy Gate

Records test results in Notion and decides if the task can advance to deploy approval.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "record_test_result:|test gate|deploy gate"
```

| Signal | Keyword |
|---|---|
| Metadata written | `record_test_result: metadata written` |
| Metadata write failed | `record_test_result: metadata write failed` |
| Advancement blocked | `record_test_result: BLOCKING advancement — metadata write for Test Status` |
| Task advanced | `record_test_result: advanced task_id=... to=...` |
| Advance failed | `record_test_result: status advance failed` |
| Not advancing (other outcome) | `record_test_result: not advancing` |
| Extended gate OK | `extended test gate task_id=... ok=... advanced=...` |
| Extended gate exception | `extended test gate raised —` |
| Gate not satisfied | `deploy gate not satisfied —` |

---

### 10. Deploy Trigger + Smoke Check

GitHub Actions workflow dispatch and post-deploy health verification.

```bash
docker compose --profile aws logs --tail=300 backend-aws 2>&1 \
  | grep -E "trigger_deploy_workflow|smoke_check:|record_smoke_check|post-deploy smoke"
```

| Signal | Keyword |
|---|---|
| Deploy workflow dispatched | `trigger_deploy_workflow: success` |
| Deploy dispatch failed | `trigger_deploy_workflow:` (error level) |
| Smoke check attempt | `smoke_check: liveness attempt` |
| Smoke check result | `smoke_check:` (summary line) |
| Smoke passed (executor) | `smoke check passed task_id=` |
| Smoke failed (executor) | `smoke check FAILED task_id=` |
| Advanced to done | `record_smoke_check_result: advanced task_id=... to done` |
| Smoke blocked task | `record_smoke_check_result: blocked task_id=` |

---

### 11. Missing Artifact Recovery

When a task is in `investigation-complete`, `ready-for-patch`, or `patching` but the investigation artifact (.md) is missing or empty, the recovery playbook attempts to regenerate from the sections sidecar or raw content, or resets the task to planned.

```bash
docker compose --profile aws logs --tail=500 backend-aws 2>&1 \
  | grep -E "agent_recovery:|missing_artifact|regenerated|reset to planned"
```

| Signal | Keyword |
|---|---|
| Playbook found tasks | `missing_artifact_playbook found` |
| Artifact valid (skip) | `artifact valid at` |
| Regenerated from sidecar | `regenerated artifact from sections` |
| Regenerated from raw | `regenerated artifact from raw content` |
| Task reset | `reset to planned` / `Investigation artifact was missing or empty` |

**Path consistency:** Recovery uses `get_writable_bug_investigations_dir()` for bug-investigations (same as apply/validate), so artifacts in the fallback path (e.g. when `docs/` is not writable) are found. If you see "No sections sidecar found" but the .md file exists, check that `AGENT_BUG_INVESTIGATIONS_DIR` or repo `docs/agents/bug-investigations` is writable and that apply and recovery use the same path.

---

### 12. Workspace Root Resolution

First log emitted on startup — confirms the writable root used for all file writes.

```bash
docker compose --profile aws logs --tail=100 backend-aws 2>&1 \
  | grep "workspace_root:"
```

| Signal | Keyword |
|---|---|
| Env var override | `workspace_root: using ATP_WORKSPACE_ROOT=` |
| Git root found | `workspace_root: found .git at` |
| Docs heuristic | `workspace_root: found docs/ at parents[` |
| Fallback to /app | `workspace_root: using fallback parents[2]=` |

Expected in Docker: either `found docs/` or `using fallback parents[2]=/app`. If you see `/` or a path outside `/app`, file writes will fail with `Permission denied`.

---

### 13. JSONL Activity Log

Structured event log persisted inside the container at `/app/logs/agent_activity.jsonl`.

```bash
docker compose --profile aws exec -T backend-aws \
  tail -50 /app/logs/agent_activity.jsonl 2>/dev/null \
  | python3 -m json.tool --no-ensure-ascii
```

Each line is a JSON object with `timestamp`, `event_type`, `task_id`, `task_title`, and `details`. Look for `event_type` values like `task_claimed`, `execution_started`, `execution_failed`, `deploy_approved`, `smoke_check_triggered`.

Search for a specific task:

```bash
docker compose --profile aws exec -T backend-aws \
  grep "TASK_ID_HERE" /app/logs/agent_activity.jsonl
```

**Note**: This file lives inside the container filesystem (not volume-mounted), so it is lost on container recreation. Back it up if needed:

```bash
docker compose --profile aws cp backend-aws:/app/logs/agent_activity.jsonl ./agent_activity_backup.jsonl
```

---

## Full Orchestration Trace (Single Command)

One command to see the entire lifecycle of any recent task from pickup to completion:

```bash
docker compose --profile aws logs --tail=2000 backend-aws 2>&1 \
  | grep -E "scheduler_cycle_start|task_detected|notion_tasks_found|_parse_page.*Type|select_default_callbacks|LIFECYCLE|CALLBACK RE-SELECTION|refreshed task type|\[TG\]\[.*APPROVAL\]|openclaw_client:|record_test_result:|BLOCKING|deploy gate|trigger_deploy|smoke_check:|workspace_root:|Cursor handoff" \
  | tail -80
```

Follow it live:

```bash
docker compose --profile aws logs -f backend-aws 2>&1 \
  | grep --line-buffered -E "scheduler_cycle|task_detected|select_default|LIFECYCLE|APPROVAL|openclaw_client|record_test_result|BLOCKING|deploy gate|trigger_deploy|smoke_check|workspace_root"
```

---

## Quick Diagnostic Commands

| What | Command |
|---|---|
| Is the backend healthy? | `curl -sS http://localhost:8002/ping_fast` |
| Container status | `docker compose --profile aws ps backend-aws` |
| Env vars inside container | `docker compose --profile aws exec -T backend-aws printenv \| grep -E "^(NOTION\|OPENCLAW\|TELEGRAM\|ATP_)" \| sed 's/=.*/=<SET>/'` |
| Last 20 errors | `docker compose --profile aws logs --tail=1000 backend-aws 2>&1 \| grep -i "ERROR" \| tail -20` |
| Permission denied? | `docker compose --profile aws logs --tail=500 backend-aws 2>&1 \| grep -i "permission denied"` |
| Pending approvals in DB | `docker compose --profile aws exec -T backend-aws python -c "from app.services.agent_telegram_approval import get_pending_approvals; import json; print(json.dumps(get_pending_approvals(), indent=2, default=str))"` |
| Restart backend | `docker compose --profile aws stop backend-aws && docker compose --profile aws up -d backend-aws` |

---

## GitHub Actions Logs

Deploy workflows triggered by the orchestrator run in GitHub Actions:

**[github.com/ccruz0/crypto-2.0/actions](https://github.com/ccruz0/crypto-2.0/actions)**

Look for `workflow_dispatch` runs. The orchestrator logs the dispatch result as `trigger_deploy_workflow: success` or `trigger_deploy_workflow:` at error level in the container logs.
