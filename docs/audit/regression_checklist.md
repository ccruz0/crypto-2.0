# Regression Checklist

This checklist should be run before deploying changes to production.

## Pre-Deploy Verification

### 1. Watchlist Performance
- [ ] Watchlist loads in < 2 seconds (or record timing)
- [ ] No duplicate symbols rendered in UI
- [ ] All watchlist coins display correctly

### 2. Alert Functionality
- [ ] Toggle BUY alert returns 200 status
- [ ] Toggle SELL alert returns 200 status
- [ ] Alert toggles respond without timeout (< 2s)
- [ ] Alert state persists after page reload

### 3. Signal Throttling
- [ ] Toggling Trade status (YES ↔ NO) resets throttle counters
- [ ] Signal throttling reset works when Trade status changes
- [ ] Throttle state persists correctly

### 4. Report Generation
- [ ] Report page shows runtime findings only
- [ ] No git errors surfaced in reports
- [ ] Reports display correctly

### 5. Setup Panel
- [ ] All strategy parameters are visible
- [ ] Strategy config saves to backend
- [ ] Strategy config persists after reload
- [ ] Changing Trade status resets cooldown counters

### 6. Backend Stability
- [ ] Backend responds to health checks
- [ ] No --reload flag in production (uses gunicorn)
- [ ] Endpoints respond quickly and consistently

### 7. Database Integrity
- [ ] No duplicate watchlist entries
- [ ] Watchlist deduplication working
- [ ] Database queries perform well

## Running the Checklist

Use the audit snapshot script to automatically verify most items:

```bash
# Local
./scripts/audit_snapshot.sh

# AWS
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && ./scripts/audit_snapshot.sh'
```

## Manual Verification

Some items require manual verification:
- Watchlist load time (check browser network tab)
- Alert toggle response time (check browser network tab)
- Report page content (visual inspection)

