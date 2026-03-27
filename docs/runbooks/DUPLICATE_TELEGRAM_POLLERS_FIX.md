# Duplicate Telegram Pollers Fix

## Problem

ATP Control bot returns:
- **"Unknown command. Use /help."** — when `/task` exists in code
- **"Already processed. Try again in a moment."** — when dedup table sees duplicate

**Root cause:** Multiple processes are polling Telegram with the **same** `TELEGRAM_BOT_TOKEN`. Each process receives updates from `getUpdates`. When two processes both receive the same update:
1. Process A processes it first, inserts into `telegram_update_dedup`, sends response
2. Process B tries to process it — dedup INSERT fails (conflict) → sends "Already processed"

"Unknown command" indicates one process has old code (no `/task` handler) while another has new code.

## Detection

### 1. Run diagnostic script on PROD

```bash
cd /home/ubuntu/crypto-2.0
bash backend/scripts/diag/detect_telegram_consumers.sh
```

Or via SSM:
```bash
aws ssm send-command --instance-ids i-087953603011543c5 --document-name AWS-RunShellScript \
  --parameters 'commands=["cd /home/ubuntu/crypto-2.0 && bash backend/scripts/diag/detect_telegram_consumers.sh"]' \
  --region ap-southeast-1
```

### 2. Check logs for poller conflicts

```bash
docker compose --profile aws logs backend-aws --tail=500 | grep -E "409|Another poller|getUpdates conflict|Telegram poller started"
```

- `[TG] Another poller is active` — advisory lock is working; another process (or worker) is polling
- `[TG] getUpdates conflict (409)` — **duplicate pollers**; another process is using the same token
- `[TG] Telegram poller started by backend-aws` — this process is the active poller

### 3. Verify polling vs webhook

```bash
# From backend container
docker compose --profile aws exec backend-aws python -c "
import os, json, urllib.request
t = (os.getenv('TELEGRAM_BOT_TOKEN') or os.getenv('TELEGRAM_BOT_TOKEN_AWS') or '').strip()
if t:
    r = urllib.request.urlopen(f'https://api.telegram.org/bot{t}/getWebhookInfo', timeout=5)
    d = json.loads(r.read())
    url = d.get('result', {}).get('url', '')
    print('Webhook:', url or 'None (polling mode)')
"
```

If webhook URL is set, polling will fail. Delete webhook to use polling.

## Fix

### Ensure ONLY backend-aws polls

| Service | RUN_TELEGRAM_POLLER | Expected |
|---------|---------------------|----------|
| `backend-aws` | `true` | **Only** poller |
| `backend-aws-canary` | `false` | Must not poll |
| `market-updater-aws` | N/A | No scheduler, no polling |

### Stop duplicate pollers

1. **Stop local backend** if running with prod token:
   ```bash
   docker compose --profile local down
   # or: stop uvicorn / python process
   ```

2. **Stop canary** if it has RUN_TELEGRAM_POLLER unset:
   ```bash
   docker compose --profile aws stop backend-aws-canary
   ```

3. **Stop old backend container** (deployment overlap):
   ```bash
   docker compose --profile aws ps -a
   # Stop any orphan backend-aws containers
   docker compose --profile aws down backend-aws
   docker compose --profile aws up -d backend-aws
   ```

4. **Verify canary env**:
   ```bash
   docker compose --profile aws exec backend-aws-canary printenv RUN_TELEGRAM_POLLER
   # Must be: false
   ```

### If deployment causes overlap

During `docker compose up -d backend-aws`, the old container may briefly overlap with the new one. Both would poll. Mitigations:
- Use `docker compose stop backend-aws && docker compose up -d backend-aws` for sequential replace
- Or accept brief overlap; advisory lock + dedup will handle it (one may get "Already processed" during overlap)

## Verification

After fix:

1. **Send `/help`** in ATP Control — must include `/task`
2. **Send `/task`** — must NOT return "Unknown command"
3. **No more "Already processed"** for normal commands

```bash
# Check only one poller is active
docker compose --profile aws logs backend-aws --tail=100 | grep "Telegram poller started"
# Should see exactly one per process (2 workers = 2 logs, but only one holds lock per cycle)
```

## Architecture

- **Polling:** `process_telegram_commands()` in `scheduler.py` → `get_telegram_updates()` in `telegram_commands.py`
- **Single-poller lock:** PostgreSQL advisory lock `TELEGRAM_POLLER_LOCK_ID = 1234567890` — only one process can hold it per cycle
- **backend-aws:** 2 gunicorn workers; both run scheduler; advisory lock serializes — only one worker polls at a time
- **backend-aws-canary:** `RUN_TELEGRAM_POLLER=false` — returns early, never acquires lock

## Startup visibility

On first successful lock acquisition, log:
```
[TG] Telegram poller started by backend-aws (pid=123 hostname=xxx RUNTIME_ORIGIN=AWS)
```

On 409 conflict:
```
[TG] getUpdates conflict (409) - Another webhook or polling client is active. Possible duplicate pollers.
```
