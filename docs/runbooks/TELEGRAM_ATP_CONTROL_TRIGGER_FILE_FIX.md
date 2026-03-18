# Fix: Permission Denied on "Run full fix now" Trigger File

## Problem

When you tap **► Run full fix now** in ATP Control (Telegram), you get:

```
⚠️ Could not write trigger file (run full fix manually on the server). Error: [Errno 13] Permission denied: '/app/logs/trigger_full_fix'
```

The backend cannot write the trigger file, so the automated full fix never runs.

## Root Cause

- The backend runs as `appuser` (UID 10001) inside the container.
- The host directory `./logs` is mounted to `/app/logs` in the container.
- If `./logs` is owned by root or ubuntu (UID 1000), the container's UID 10001 has no write permission.

## Solution

On the EC2 host (or wherever the stack runs), make `./logs` writable by UID 10001:

```bash
cd /home/ubuntu/automated-trading-platform
sudo mkdir -p logs
sudo chown 10001:10001 logs
```

Then restart the backend so it picks up the volume mount (optional; ownership change is immediate):

```bash
docker compose --profile aws restart backend-aws backend-aws-canary
```

## Verification

1. Tap **► Run full fix now** again in ATP Control.
2. You should see: `✅ Full fix triggered. It will run on the next health check (within ~5 min). You'll get ✅ recovered when health returns.`
3. On the host, confirm the trigger file was created:
   ```bash
   ls -la /home/ubuntu/automated-trading-platform/logs/trigger_full_fix
   ```

## One-Liner (SSM or SSH)

```bash
cd /home/ubuntu/automated-trading-platform && sudo mkdir -p logs && sudo chown 10001:10001 logs
```

## Related

- Trigger file path: `ATP_TRIGGER_FULL_FIX_PATH` (default `/app/logs/trigger_full_fix`)
- Same pattern as `secrets/runtime.env`: `chown 10001:10001` for backend writability
- Runbook: [ATP_HEALTH_ALERT_STREAK_FAIL.md](ATP_HEALTH_ALERT_STREAK_FAIL.md)
