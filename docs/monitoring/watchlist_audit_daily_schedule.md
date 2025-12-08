# Daily Watchlist Audit Schedule

**Last Updated:** 2025-12-01  
**Status:** ✅ Configured

## Overview

The Watchlist audit tests are configured to run automatically every day at 2:00 AM Bali time (UTC+8, Asia/Makassar timezone).

## Setup

### 1. Install Dependencies

Ensure Node.js, npm, and Playwright are installed:

```bash
cd frontend
npm install
npx playwright install chromium
```

### 2. Configure Cron Job

Run the setup script:

```bash
bash scripts/setup_watchlist_audit_cron.sh
```

This will:
- Add a cron job that runs daily at 2 AM Bali time
- Configure timezone to Asia/Makassar (UTC+8)
- Set up logging to `logs/cron_audit.log`

### 3. Manual Setup (Alternative)

If you prefer to set up the cron job manually:

```bash
crontab -e
```

Add this line:

```
0 2 * * * TZ=Asia/Makassar cd /path/to/automated-trading-platform && bash scripts/run_watchlist_audit_daily.sh >> logs/cron_audit.log 2>&1
```

**Note**: Replace `/path/to/automated-trading-platform` with the actual path to your project.

## Schedule Details

- **Time**: 2:00 AM daily
- **Timezone**: Asia/Makassar (Bali, UTC+8)
- **UTC Equivalent**: 18:00 UTC (previous day)
- **Script**: `scripts/run_watchlist_audit_daily.sh`

## Logs and Reports

### Log Files

- **Daily Log**: `logs/watchlist_audit_YYYYMMDD_HHMMSS.log`
- **Cron Log**: `logs/cron_audit.log`
- **Summary**: `logs/watchlist_audit_summary.txt`

### HTML Reports

- **Location**: `logs/watchlist_audit_reports/`
- **Format**: `report_YYYYMMDD_HHMMSS.html`
- **Retention**: Last 30 days (older reports are automatically deleted)

## Manual Execution

You can run the audit tests manually at any time:

```bash
# From project root
bash scripts/run_watchlist_audit_daily.sh

# Or from frontend directory
cd frontend
DASHBOARD_URL=https://dashboard.hilovivo.com API_BASE_URL=https://dashboard.hilovivo.com/api npm run test:e2e:watchlist-audit
```

## Monitoring

### Check Cron Job Status

```bash
# View current crontab
crontab -l

# View cron logs
tail -f logs/cron_audit.log

# View latest test results
cat logs/watchlist_audit_summary.txt

# View latest HTML report
ls -lt logs/watchlist_audit_reports/ | head -5
```

### Check Test Results

```bash
# View latest log
ls -t logs/watchlist_audit_*.log | head -1 | xargs cat

# View summary
cat logs/watchlist_audit_summary.txt

# Open latest HTML report
open logs/watchlist_audit_reports/$(ls -t logs/watchlist_audit_reports/*.html | head -1)
```

## Troubleshooting

### Cron Job Not Running

1. **Check cron service**:
   ```bash
   # On Linux
   sudo systemctl status cron
   
   # On macOS
   sudo launchctl list | grep cron
   ```

2. **Check cron logs**:
   ```bash
   # On Linux
   grep CRON /var/log/syslog
   
   # On macOS
   grep cron /var/log/system.log
   ```

3. **Verify script permissions**:
   ```bash
   ls -l scripts/run_watchlist_audit_daily.sh
   # Should show: -rwxr-xr-x
   ```

4. **Test script manually**:
   ```bash
   bash scripts/run_watchlist_audit_daily.sh
   ```

### Timezone Issues

If tests are running at the wrong time:

1. **Verify timezone in cron**:
   ```bash
   crontab -l | grep TZ
   # Should show: TZ=Asia/Makassar
   ```

2. **Check system timezone**:
   ```bash
   date
   timedatectl  # On Linux
   ```

3. **Test timezone**:
   ```bash
   TZ=Asia/Makassar date
   ```

### Test Failures

If tests fail:

1. **Check latest log**:
   ```bash
   tail -100 logs/watchlist_audit_*.log | tail -1
   ```

2. **Check HTML report**:
   ```bash
   open logs/watchlist_audit_reports/$(ls -t logs/watchlist_audit_reports/*.html | head -1)
   ```

3. **Run manually to debug**:
   ```bash
   cd frontend
   DASHBOARD_URL=https://dashboard.hilovivo.com API_BASE_URL=https://dashboard.hilovivo.com/api npm run test:e2e:watchlist-audit --headed
   ```

## Removing the Cron Job

To remove the scheduled cron job:

```bash
# Edit crontab
crontab -e

# Remove the line containing "run_watchlist_audit_daily.sh"
# Save and exit
```

Or use the command:

```bash
crontab -l | grep -v "run_watchlist_audit_daily.sh" | crontab -
```

## Email Notifications (Optional)

To receive email notifications on test failures, you can modify the script to send emails:

```bash
# Add to run_watchlist_audit_daily.sh after test execution
if [ $TEST_EXIT_CODE -ne 0 ]; then
    echo "Tests failed. Check logs at $LOG_FILE" | mail -s "Watchlist Audit Failed" your-email@example.com
fi
```

## References

- **Test Suite**: `frontend/tests/e2e/watchlist_audit.spec.ts`
- **Audit Script**: `scripts/run_watchlist_audit_daily.sh`
- **Setup Script**: `scripts/setup_watchlist_audit_cron.sh`
- **Audit Status**: `docs/monitoring/watchlist_audit_status.md`











