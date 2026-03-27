# LAB: Notion → OpenClaw → PATCH loop verification

**Goal:** Confirm the full loop works on LAB without manual secrets: Notion pickup → execution mode (Normal/Strict) → strict proof validation → PATCH task creation.

**Prerequisite:** SSM parameter `/automated-trading-platform/lab/notion/api_key` exists and LAB instance role has `ssm:GetParameter` (and decryption). No manual key input required at runtime.

---

## System self-healing behavior

- **Pre-flight (every scheduler cycle):** Before each pickup, the backend checks `NOTION_API_KEY` and `NOTION_TASK_DB`. If missing, it **automatically** tries to repair by fetching the API key from SSM (`/automated-trading-platform/lab/notion/api_key`), writing to `.env.aws` and `secrets/runtime.env`, and setting process env. Log: `notion_env auto_repair_triggered source=ssm_repair`.
- **Startup:** Backend validates Notion env at startup and logs `notion_startup_validation NOTION_API_KEY=... NOTION_TASK_DB=...`. If missing, integration is marked **degraded** (no crash).
- **Retry:** If pickup fails due to env, the cycle is skipped and repair is attempted; the next cycle can succeed. Notion API calls (task read) are retried with backoff (max 3 attempts).
- **Health:** `GET /api/health/notion` returns `env_ok`, `last_pickup_status`, `last_error` (no secrets).

---

## If SSM fails

- If the LAB instance role cannot read the SSM parameter, auto-repair will not set env. Scheduler cycles will return `reason: notion_env_missing` and log `skipping cycle NOTION_env=missing`.
- **Fix:** Create the parameter (from a machine with AWS CLI): `./scripts/aws/store_lab_notion_api_key_ssm.sh`, or add the LAB instance role policy `ssm:GetParameter` (and `kms:Decrypt` if using a custom key) for `/automated-trading-platform/lab/notion/*`.
- **Temporary:** On the LAB host, run `./scripts/aws/fix_notion_env_lab.sh` (if you have another way to populate SSM) or add `NOTION_API_KEY` and `NOTION_TASK_DB` to `.env.aws` and run `bash scripts/aws/render_runtime_env.sh` then restart backend-aws.

---

## Debug in &lt;2 minutes

1. **Env and last pickup:**  
   `curl -s http://127.0.0.1:8002/api/health/notion`  
   Check `env_ok`, `last_pickup_status`, `last_error`.

2. **Structured logs (grep-friendly):**  
   `docker compose --profile aws logs backend-aws 2>&1 | grep -E "notion_task_detected|selected_task_for_execution|execution_mode|strict_proof_passed|strict_proof_failed|patch_task_created|notion_preflight|auto_repair_triggered"`

3. **Diagnostic script (no secrets):**  
   `./scripts/diagnostics/check_notion_env.sh`

4. **One pickup (no Notion writes):**  
   `AGENT_DRY_RUN=1 ./scripts/run_notion_task_pickup.sh`  
   Simulates pickup and strict validation without updating Notion.

---

## 1. Verify environment on LAB

Run from **repo root on the LAB host** (e.g. after SSM Session Manager or SSH).

### 1.1 Diagnostic (no secrets printed)

```bash
cd /home/ubuntu/crypto-2.0
./scripts/diagnostics/check_notion_env.sh
```

**Expected (OK):** Exit 0, output includes:
- `NOTION_API_KEY: present (source: ...)`
- `NOTION_TASK_DB: present (source: ...)`

**If missing:** Exit 1 and recommendation to run `./scripts/aws/fix_notion_env_lab.sh`.

### 1.2 Auto-repair (if diagnostic reported missing)

```bash
./scripts/aws/fix_notion_env_lab.sh
```

**Expected:** Lines like “Updated .env.aws”, “Rendered secrets/runtime.env”, “Restarted backend-aws”, “Container NOTION_API_KEY: present”, “Container NOTION_TASK_DB: present”, then “fix_notion_env_lab: done.”

### 1.3 Env inside backend-aws (no secret values)

```bash
docker compose --profile aws exec backend-aws sh -c 'echo "NOTION_API_KEY: $(test -n "$NOTION_API_KEY" && echo present || echo missing)"; echo "NOTION_TASK_DB: $(test -n "$NOTION_TASK_DB" && echo present || echo missing)"'
docker compose --profile aws exec backend-aws printenv NOTION_TASK_DB
```

**Expected:** `NOTION_API_KEY: present`, `NOTION_TASK_DB: present`, and the DB ID printed (e.g. `eb90cfa139f94724a8b476315908510a`). Do **not** print `NOTION_API_KEY` value.

---

## 2. Verify runtime wiring

- **render_runtime_env.sh** writes `NOTION_API_KEY` and `NOTION_TASK_DB` into `secrets/runtime.env` when available (prod SSM, then LAB SSM, then .env.aws; default task DB used on LAB when only API key is in SSM).
- **docker-compose.yml** loads `./secrets/runtime.env` (and `.env.aws`) into `backend-aws` via `env_file`.
- **Backend** reads `NOTION_API_KEY` and `NOTION_TASK_DB` from `os.environ` / `app.core.config.settings` (e.g. `notion_task_reader._get_config()`, `notion_tasks._get_config()`).

No extra steps if diagnostic and container checks above pass.

---

## 3. One Notion pickup cycle

```bash
cd /home/ubuntu/crypto-2.0
./scripts/run_notion_task_pickup.sh
```

**Expected:** No “NOTION_API_KEY not set”; script runs the scheduler cycle inside the container; JSON output with `ok`, `action`, and optionally `task_id` / `task_title`. If a task was picked: `action` like `extended_execution_started` or approval sent.

**If you have a specific task ID (e.g. from Notion):**

```bash
TASK_ID=<notion-page-id> ./scripts/run_notion_task_pickup.sh
```

---

## 4. Full cycle: Planned + Strict → PATCH task

**Input (in Notion):** One task with:

- **Status** = `Planned` (exact Select option name)
- **Execution Mode** = `Strict` (Select or rich_text; reader accepts both)
- **Type** = any (e.g. Bug or Patch)

**Expected flow:**

1. **Pickup:** `run_notion_task_pickup.sh` → `run_agent_scheduler_cycle` → `prepare_task_with_approval_check` → `prepare_next_notion_task` (or `prepare_task_by_id`) → `get_high_priority_pending_tasks` → `get_pending_notion_tasks`. Task appears (Status filter uses “Planned”).
2. **Execution:** manual_only + approval_required → `execute_prepared_task_if_approved`; OpenClaw runs; callback writes artifact to `docs/agents/bug-investigations/notion-bug-<task_id>.md`.
3. **Strict gate:** Before advancing to investigation-complete, `execution_mode == "strict"` → `get_artifact_content_for_task(task_id)` → `validate_strict_mode_proof(artifact_body)`.
4. **If proof passes:** `create_patch_task_from_investigation` → `create_notion_task(..., type="Patch", status="planned", source="OpenClaw")` → new Notion page with Type=Patch, Status=Planned.
5. **Status:** Investigation task moves to Investigation Complete; Telegram investigation-complete message sent.

**Verify PATCH task created (in Notion or via API):** New task with title “PATCH: …”, Type=Patch, Status=Planned, Source=OpenClaw.

---

## 5. Commands summary

| Step | Command | Expected |
|------|--------|----------|
| Env diagnostic | `./scripts/diagnostics/check_notion_env.sh` | Exit 0; NOTION_* present |
| Auto-repair (if needed) | `./scripts/aws/fix_notion_env_lab.sh` | Env updated, backend restarted, container vars present |
| Env in container | `docker compose --profile aws exec backend-aws printenv NOTION_TASK_DB` | DB ID printed |
| One pickup | `./scripts/run_notion_task_pickup.sh` | No NOTION_API_KEY error; scheduler output |
| Pickup by ID | `TASK_ID=<id> ./scripts/run_notion_task_pickup.sh` | Same, for specific task |

---

## 6. Root cause reference (if something fails)

- **NOTION_* missing in container:** Run `fix_notion_env_lab.sh`; ensure SSM parameter exists and instance role can read it; re-run `render_runtime_env.sh` and restart backend.
- **“NOTION_API_KEY not set” in logs:** Env not in container → fix as above; confirm `secrets/runtime.env` contains the vars and is mounted (compose `env_file` + volume).
- **No tasks found:** Notion Status must be exact “Planned” (or other pickable option); Type=Patch tasks are eligible; NOTION_TASK_DB must match the AI Task System database ID.
- **Execution Mode ignored:** Property name “Execution Mode” (or “execution_mode” / “ExecutionMode”); reader supports Select and rich_text; normalized to “normal” or “strict”.
- **Strict proof blocks advance:** Artifact must exist at `docs/agents/bug-investigations/notion-bug-<task_id>.md` with body ≥200 chars; content must satisfy `validate_strict_mode_proof` (file path, function, code block, root cause, fix, validation).
- **PATCH task not created:** Check logs for “create_patch_task_from_investigation”; ensure Notion API key and DB ID allow create; dedup cooldown may skip duplicate (same title/project/type/details within window).
