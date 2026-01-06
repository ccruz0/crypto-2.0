# Quick Fix: Backend Health Error

## Problem
Dashboard shows: **"Backend Health: ERROR"** with message:
> "Backend service temporarily unavailable. Please ensure services are running."

## Quick Solution

### Option 1: Use the Diagnostic Script (Easiest)

**From your local machine:**
```bash
# Just diagnose the issue
./diagnose_backend_health.sh

# Diagnose AND automatically fix
./diagnose_backend_health.sh --fix
```

**On AWS server:**
```bash
cd ~/automated-trading-platform
./diagnose_backend_health.sh --fix
```

### Option 2: Manual Restart (Quick Fix)

**SSH into AWS server:**
```bash
ssh ubuntu@54.254.150.31
cd ~/automated-trading-platform
docker compose --profile aws restart backend-aws
```

**Or use the restart script from local:**
```bash
./restart_backend_aws.sh
```

### Option 3: Use Dashboard Restart Button

If the backend is partially working:
1. Go to Monitoring tab in dashboard
2. Click "Reiniciar Backend" button
3. Wait 30-60 seconds
4. Refresh the page

## Verify Fix

After restarting, check:

1. **Container status:**
   ```bash
   docker compose --profile aws ps backend-aws
   ```
   Should show "Up" and "(healthy)"

2. **Health endpoint:**
   ```bash
   curl -s http://localhost:8002/ping_fast
   ```
   Should return quickly

3. **Dashboard:**
   - Refresh the Monitoring tab
   - Backend Health should show "HEALTHY" (green) instead of "ERROR" (red)

## What the Diagnostic Script Does

The `diagnose_backend_health.sh` script automatically:

1. ✅ Checks if backend container is running
2. ✅ Tests health endpoints (`/ping_fast`, `/health`, `/api/monitoring/summary`)
3. ✅ Shows recent logs and errors
4. ✅ Checks database connection
5. ✅ Verifies port availability
6. ✅ Provides fix options

## Common Causes

- **Container stopped/crashed** → Restart fixes it
- **Database connection lost** → Restart database first, then backend
- **Port conflict** → Check what's using port 8002
- **Out of memory** → Check system resources

## Need More Help?

See detailed guide: `BACKEND_HEALTH_FIX.md`




