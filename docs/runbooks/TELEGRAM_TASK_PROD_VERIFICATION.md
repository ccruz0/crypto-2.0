# Production verification — `/task` → Notion (direct write)

Use after deploy or Notion/Telegram config changes.

## 1. Send Telegram (ATP Control)

In the **ATP Control** chat (authorized in `TELEGRAM_*` env):

```text
/task Verify prod Notion intake <timestamp>
```

**Expect:** a **single** reply starting with **“Task created in Notion”** (or dedup message if you sent the same text twice within the cooldown window).

**Not expected:** “Unknown command”, generic “Notion unavailable” while Notion is configured.

---

## 2. Confirm Notion

Open the **AI Task System** database and find a row whose **Task** title matches the first line of your message (or search for `Verify prod Notion`).

---

## 3. Logs (backend-aws)

On the host or via log aggregation, grep for:

```bash
# Container logs (example)
docker compose --profile aws logs backend-aws 2>&1 | tail -500 | grep -E '\[TG\]\[TASK\]|notion_create|notion_sync_failed|Notion task created'
```

**Success signals:**

- `[TG][TASK] intake`
- `[TG][TASK] notion_create_attempt`
- `[TG][TASK] notion_create_success`
- `Notion task created: id=...`

**Failure signals:**

- `[TG][TASK] notion_create_failure`
- `notion_sync_failed status=...`
- `notion_preflight_failed` (missing `NOTION_API_KEY` / `NOTION_TASK_DB`)

---

## 4. HTTP health (optional)

```bash
curl -sS -o /dev/null -w '%{http_code}\n' --connect-timeout 5 https://dashboard.hilovivo.com/api/health
```

Expect `200`.

---

## 5. If something fails

| Symptom | Check |
|--------|--------|
| “Not authorized” | `TELEGRAM_AUTH_USER_ID` / `TELEGRAM_CHAT_ID` / `TELEGRAM_ATP_CONTROL_CHAT_ID` vs `[TG][AUTH][DENY]` |
| HTTP 401/403 in logs | Notion integration token; DB shared with integration |
| Duplicate replies | [DUPLICATE_TELEGRAM_POLLERS_FIX.md](DUPLICATE_TELEGRAM_POLLERS_FIX.md) |
| Wrong bot answering | Which token is polling (`[TG][CONFIG]`, `token_source`) |

---

## 6. Deploy latest `main` (after you push)

**Option A — from your laptop (AWS CLI + SSM):**

- **Backend:** `./scripts/deploy_production_via_ssm.sh`  
  - Faster recycle: `SKIP_REBUILD=1 ./scripts/deploy_production_via_ssm.sh`  
  - Stale image issues: `NO_CACHE=1 ./scripts/deploy_production_via_ssm.sh`  
  - Long builds: `MAX_WAIT_ITERATIONS=900` (see script header).
- **Frontend** (separate submodule image): `./deploy_frontend_ssm.sh`  
  - That script `git pull`s inside `frontend/` and rebuilds **`frontend-aws`**.

**Option B — on the EC2 host (repo root),** if you shell in:

```bash
export HOME=/home/ubuntu
git config --global --add safe.directory /home/ubuntu/automated-trading-platform 2>/dev/null || true
cd /home/ubuntu/automated-trading-platform
git fetch origin && git reset --hard origin/main
git submodule update --init --recursive
docker compose --profile aws build backend-aws frontend-aws
docker compose --profile aws up -d backend-aws frontend-aws
```

Then run **§1–§4** again.

---

See also: [TELEGRAM_TASK_COMMAND_DEBUG.md](TELEGRAM_TASK_COMMAND_DEBUG.md), [TELEGRAM_TASK_INTAKE.md](TELEGRAM_TASK_INTAKE.md).
