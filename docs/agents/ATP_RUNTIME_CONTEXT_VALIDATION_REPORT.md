# ATP Runtime Context Prompt Injection — Validation Report

**Date:** 2025-03-15  
**Scope:** Validate that ATP investigations use pre-fetched runtime context instead of attempting local docker/sudo commands.

---

## A. Deployed Paths Verified

| Builder | File | Line | Calls `_fetch_atp_runtime_context()` |
|---------|------|------|-------------------------------------|
| `build_investigation_prompt` | `backend/app/services/openclaw_client.py` | 523 | ✓ |
| `build_monitoring_prompt` | `backend/app/services/openclaw_client.py` | 579 | ✓ |
| `build_telegram_alerts_prompt` | `backend/app/services/openclaw_client.py` | 612 | ✓ |
| `build_execution_state_prompt` | `backend/app/services/openclaw_client.py` | 656 | ✓ |

**Flow:** `agent_callbacks._openclaw_fallback` → `prompt_builder_fn(prepared_task)` → `user_prompt, instructions` → `_call_openclaw_once` → `send_to_openclaw`.

All four builders prepend runtime context when `_fetch_atp_runtime_context()` returns non-empty (always, since it adds "unavailable" blocks on SSM failure).

---

## B. Prompt Evidence

**Local validation (boto3 not installed):**

```bash
cd ~/automated-trading-platform && source .venv/bin/activate && cd backend && PYTHONPATH=. python3 -c "
from app.services.openclaw_client import build_investigation_prompt
mock = {'task': {'id': 't', 'task': 'Test', 'details': 'docker denied'}, 'repo_area': {}}
up, inst = build_investigation_prompt(mock)
print('HAS_RUNTIME:', 'Pre-fetched runtime context' in up)
print('HAS_FORBID:', 'NEVER run docker' in inst)
print('--- PROMPT PREVIEW ---')
print(up[:600])
"
```

**Result:**
- `HAS_RUNTIME: True`
- `HAS_FORBID: True`
- Prompt starts with:
  ```
  ## Pre-fetched runtime context (do NOT run docker/sudo — use this)

  ### ATP PROD: unavailable (boto3 not installed)

  ### LAB: unavailable (boto3 not installed)

  ---

  Investigate the following bug report...
  ```

**Note:** The prompt uses `## Pre-fetched runtime context` and `### ATP PROD` / `### LAB` (not `## ATP Runtime Context (PROD)`). On PROD with AWS/SSM, the blocks will contain actual `docker compose --profile aws ps` and `docker ps` output.

---

## C. Log Evidence

**Before fix:** OpenClaw logs showed:
- `docker: Permission denied`
- `sudo: Permission denied`

**After fix (expected):**
- No new entries for those errors when ATP investigations run
- OpenClaw receives the pre-fetched context in the prompt and has no need to run docker/sudo locally

**How to verify on LAB:**
```bash
# On LAB (atp-lab-ssm-clean), after an investigation:
docker logs openclaw 2>&1 | grep -E "Permission denied|docker|sudo" | tail -20
```
Expect: no new permission-denied lines for investigation flows.

---

## D. Behavior Before vs After

| Aspect | Before | After |
|--------|--------|-------|
| Prompt content | No runtime context | Pre-fetched PROD + LAB docker output prepended |
| OpenClaw tools | Shell tool → tries `docker ps` → fails | No need; context already in prompt |
| Instructions | Generic workspace note | `CRITICAL: NEVER run docker, sudo...` |
| Evidence source | Agent attempts local commands | Agent uses prompt content + file reads |

---

## E. Remaining Gaps / Validation Steps

1. **Run real investigation on PROD**
   - Deploy backend to PROD (with boto3 + AWS credentials).
   - Trigger a bug/monitoring investigation (scheduler or manual Notion task).
   - Confirm `_fetch_atp_runtime_context()` returns real PROD/LAB output (not "unavailable").

2. **Capture constructed prompt on PROD**
   - Add temporary debug log in `agent_callbacks._openclaw_fallback` after line 811:
     ```python
     logger.info("openclaw_prompt_preview task_id=%s len=%d has_runtime=%s",
                 task_id, len(user_prompt), "Pre-fetched runtime" in user_prompt)
     ```
   - Or run the inline Python snippet above on PROD (with `PYTHONPATH` and venv) to see the prompt with real SSM data.

3. **Inspect OpenClaw logs after run**
   - On LAB: `docker logs openclaw 2>&1 | tail -200`
   - Confirm no `docker: Permission denied` or `sudo: Permission denied` for the investigation.

4. **Inspect investigation result**
   - Check `docs/agents/bug-investigations/` or `docs/runbooks/triage/` for the new artifact.
   - Confirm it cites the pre-fetched runtime block (e.g. container names, status) and does not suggest "run docker ps manually" or "SSH and run sudo".

---

## Validation Script (run on PROD or with AWS env)

```bash
cd /home/ubuntu/crypto-2.0/backend   # or your backend path
source ../.venv/bin/activate
PYTHONPATH=. python3 -c "
from app.services.openclaw_client import build_investigation_prompt

mock = {
    'task': {'id': 'val-1', 'task': 'Validate runtime context', 'details': 'docker denied'},
    'repo_area': {'area_name': 'backend', 'likely_files': [], 'relevant_docs': []},
}
up, inst = build_investigation_prompt(mock)
print('=== RUNTIME IN PROMPT ===')
print('Pre-fetched runtime context' in up)
print()
print('=== PROMPT (first 1200 chars) ===')
print(up[:1200])
print()
print('=== FORBID NOTE IN INSTRUCTIONS ===')
print('NEVER run docker' in inst)
"
```

On PROD with AWS credentials, you should see actual docker output in the prompt instead of "unavailable".
