# Eliminate zombie growth — evidence-first run

**Repo:** `/home/ubuntu/automated-trading-platform`  
**Goal:** Prove zombie parent → apply minimal fix (Python healthchecks) → verify count stops increasing.  
**Constraints:** No secrets printed; no port/nginx/business-logic changes; keep healthcheck interval/retries/start_period/timeout.

**Important:** Never run raw `docker compose config` on EC2 — it prints resolved env values. Use `scripts/aws/safe_compose_check.sh` to validate; use `scripts/aws/safe_compose_render_no_secrets.sh` only if you need a redacted config.

---

## Step A — Evidence command (copy-paste)

Run on EC2:

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/evidence_zombie_ppids.sh
```

Or run manually:

```bash
cd /home/ubuntu/automated-trading-platform

# Zombie list (small sample)
ps -eo stat,ppid,pid,cmd | awk '$1 ~ /Z/ {print}' | head -60

# Top zombie parent PIDs
ps -eo ppid,stat,cmd | awk '$2 ~ /Z/ {print $1}' | sort | uniq -c | sort -nr | head -10

# For the top 3 PPIDs, show owners
for p in $(ps -eo ppid,stat,cmd | awk '$2 ~ /Z/ {print $1}' | sort | uniq -c | sort -nr | head -3 | awk '{print $2}'); do
  echo "=== PPID $p ==="
  ps -p "$p" -o pid,ppid,stat,cmd
done

# List containerd-shim processes
ps aux | grep containerd-shim | grep -v grep | head -20
```

**Decision rule:**

- If top zombie PPIDs match containerd-shim PIDs → proceed to Step B.
- Else stop: report **INSUFFICIENT EVIDENCE** and include the top 5 PPID mappings (pid + cmd).

---

## Step B — Patch: replace bash healthchecks with Python one-liners

**Already applied** in `docker-compose.yml`:

1. **backend-aws**  
   - Before: `["CMD", "bash", "/app/scripts/aws/zombie_monitor.sh", "--check-portfolio", "http://localhost:8002/api/dashboard/state"]`  
   - After: `["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8002/ping_fast', timeout=5)"]`  
   - interval 120s, timeout 20s, retries 5, start_period 180s unchanged.

2. **market-updater-aws**  
   - Before: `["CMD", "bash", "/app/scripts/aws/zombie_monitor.sh"]`  
   - After: `["CMD", "python", "-c", "print('ok')"]`  
   - interval 60s, timeout 15s, retries 3, start_period 30s unchanged.

Confirm only healthcheck `test` entries changed for those two services:

```bash
git diff -- docker-compose.yml | grep -A2 -B2 "healthcheck\|ping_fast\|print('ok')"
```

---

## Step C — Deploy commands (copy-paste)

On EC2, using `safe_compose_check.sh` (do not run raw `docker compose config`):

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/safe_compose_check.sh
docker compose --profile aws up -d --build backend-aws market-updater-aws
docker compose --profile aws ps
```

---

## Step D — Verification command (copy-paste)

Run the verification script (baseline + 10 × date/count at 60s + health check):

```bash
cd /home/ubuntu/automated-trading-platform
bash scripts/aws/verify_zombie_count_stable.sh
```

Or manually:

```bash
for i in {1..10}; do
  date
  ps -eo stat | awk '$1 ~ /Z/ {c++} END{print "zombies:", c+0}'
  sleep 60
done
```

Health:

```bash
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8002/health
docker compose --profile aws ps | sed -n '1,8p'
```

**PASS criteria:**

- Zombie count does not increase each minute.
- backend-aws and market-updater-aws remain healthy.
- `/health` returns 200.

---

## Step E — Output format

Fill in after running:

| Item | Value |
|------|--------|
| **Root cause** | confirmed / rejected |
| **Evidence** | Top zombie PPIDs + owner commands (from Step A) |
| **Patch summary** | backend-aws: bash→python ping_fast; market-updater-aws: bash→python print('ok'). Interval/retries/start_period/timeout unchanged. |
| **Deploy commands run** | `safe_compose_check.sh`; `docker compose --profile aws up -d --build backend-aws market-updater-aws`; `docker compose --profile aws ps` |
| **Verification** | Zombie counts per minute (list 10 values) + health status (healthy/200) |

If Step A shows top PPIDs ≠ containerd-shim: **INSUFFICIENT EVIDENCE** — report top 5 PPID mappings (pid + cmd).

---

## Rollback

If the fix causes issues, restore the previous healthcheck `test` lines and redeploy:

1. **backend-aws** — set healthcheck test back to:
   ```yaml
   test: ["CMD", "bash", "/app/scripts/aws/zombie_monitor.sh", "--check-portfolio", "http://localhost:8002/api/dashboard/state"]
   ```
2. **market-updater-aws** — set healthcheck test back to:
   ```yaml
   test: ["CMD", "bash", "/app/scripts/aws/zombie_monitor.sh"]
   ```
3. Redeploy:
   ```bash
   cd /home/ubuntu/automated-trading-platform
   docker compose --profile aws up -d backend-aws market-updater-aws
   docker compose --profile aws ps
   ```

---

## Operator output format (paste results here)

| Field | Value |
|-------|--------|
| **Root cause** | confirmed / rejected |
| **Evidence** | Top PPIDs + owner commands (from Step A) |
| **Patch summary** | backend-aws test → python ping_fast; market-updater-aws test → python print('ok') |
| **Deploy commands run** | safe_compose_check + compose up backend-aws market-updater-aws + ps |
| **Verification** | 10 zombie counts + health (PASS/FAIL) |
