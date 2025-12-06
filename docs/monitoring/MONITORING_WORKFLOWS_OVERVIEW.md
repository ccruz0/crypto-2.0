# Monitoring Workflows Overview

## Purpose

The Monitoring Workflows feature provides a centralized view of all automated monitoring workflows in the system. It allows you to:

- View all workflows and their current status
- See when workflows last ran
- Manually trigger workflows that support it
- Access workflow reports directly

## Location

The "Monitoring Workflows" box is located in the **Monitoring tab** of the Dashboard. It appears as a white card with a table showing all workflows.

## Workflow Status Badges

The status column displays color-coded badges:

- **OK** (green): Last execution completed successfully
- **FAILED** (red): Last execution encountered an error
- **Never run** (gray): Workflow has not been executed yet
- **Unknown** (gray): Status could not be determined

## Manual Execution

### Running a Workflow

1. Find the workflow in the table
2. Click the **"Run now"** button in the Actions column
3. The button will show "Running..." while the workflow starts
4. A success message "Job started" will appear briefly
5. The workflow runs in the background (non-blocking)

**Note**: Not all workflows support manual execution. If a workflow doesn't have a "Run now" button, it cannot be triggered manually.

### After Running

- The workflow executes asynchronously in the background
- Status and "Last Run" will update automatically after completion
- Check the report (if available) to see results

## Viewing Reports

### Opening a Report

1. Find the workflow in the table
2. If a report is available, an **"Open report"** link appears in the Actions column
3. Click the link to open the report in a new browser tab

**Note**: Reports are only available for workflows that generate them (e.g., Watchlist Consistency Check).

## Available Workflows

### Watchlist Consistency Check

- **Schedule**: Nightly at 03:00 (Bali time)
- **Purpose**: Compares backend vs watchlist for all symbols
- **Manual Trigger**: ✅ Supported
- **Report**: ✅ Available (Markdown format)
- **Report Location**: `docs/monitoring/watchlist_consistency_report_latest.md`

### Daily Summary

- **Schedule**: Daily at 8:00 AM
- **Purpose**: Sends daily portfolio and trading activity summary
- **Manual Trigger**: ❌ Not supported
- **Report**: ❌ Not available

### Sell Orders Report

- **Schedule**: Daily at 7:00 AM (Bali time)
- **Purpose**: Reports pending sell orders
- **Manual Trigger**: ❌ Not supported
- **Report**: ❌ Not available

### SL/TP Check

- **Schedule**: Daily at 8:00 AM
- **Purpose**: Verifies positions without Stop Loss or Take Profit orders
- **Manual Trigger**: ❌ Not supported
- **Report**: ❌ Not available

### Telegram Commands

- **Schedule**: Continuous (every second)
- **Purpose**: Processes Telegram commands
- **Manual Trigger**: ❌ Not supported (continuous process)
- **Report**: ❌ Not available

### Dashboard Snapshot

- **Schedule**: Every 60 seconds
- **Purpose**: Updates dashboard snapshot for performance
- **Manual Trigger**: ❌ Not supported (continuous process)
- **Report**: ❌ Not available

## Troubleshooting

### "Run now" Button Not Working

- Check that the workflow supports manual execution
- Verify the backend is running and accessible
- Check browser console for error messages
- The workflow may already be running (wait for it to complete)

### Status Shows "FAILED"

1. Check the workflow's last execution report (if available)
2. Review backend logs for error details
3. Verify all dependencies are available (database, API endpoints, etc.)
4. Try running the workflow manually again

### Report Not Opening

- Verify the report file exists at the expected path
- Check that the backend has write permissions to the reports directory
- Ensure the workflow completed successfully (failed runs may not generate reports)

### Status Not Updating

- The workflows list auto-refreshes every 20 seconds
- Click the "Refresh" button at the top of the Monitoring tab to force an update
- Check that the backend is running and the API is accessible

## Technical Details

### API Endpoints

- **GET `/api/monitoring/workflows`**: Returns list of all workflows with status
- **POST `/api/monitoring/workflows/{workflow_id}/run`**: Triggers a workflow manually

### Workflow Registry

Workflows are defined in `backend/app/monitoring/workflows_registry.py`. To add a new workflow:

1. Add an entry to the `WORKFLOWS` list
2. Include `run_endpoint` if manual execution is supported
3. Update this documentation

### Report Paths

Reports are stored in `docs/monitoring/` relative to the project root. The API returns relative paths that the frontend can access directly.

## Related Documentation

- `WATCHLIST_CONSISTENCY_WORKFLOW.md` - Detailed documentation for the watchlist consistency workflow
- `watchlist_consistency_final_check.md` - Audit report for the consistency workflow






