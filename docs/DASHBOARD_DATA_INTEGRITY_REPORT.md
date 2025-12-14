# Dashboard Data Integrity Report System

## Overview

The Dashboard Data Integrity Report system provides a clean, user-friendly interface for viewing data integrity check results without exposing GitHub Actions failure UI.

## Architecture

### 1. GitHub Actions Workflow
- **File**: `.github/workflows/dashboard-data-integrity.yml`
- **Function**: Generates consolidated JSON report from individual discrepancy files
- **Output**: `frontend/reports/dashboard-data-integrity.json`
- **Artifact**: `dashboard-data-integrity-report`
- **Auto-posts**: Report to backend endpoint after generation

### 2. Backend API
- **File**: `backend/app/api/routes_reports.py`
- **Endpoints**:
  - `POST /api/reports/dashboard-data-integrity` - Store report (protected by `X-Report-Secret` header)
  - `GET /api/reports/dashboard-data-integrity/latest` - Get latest report
  - `GET /api/reports/dashboard-data-integrity/{run_id}` - Get specific report
- **Storage**: In-memory cache (keeps latest 10 reports)

### 3. Frontend Report Page
- **File**: `frontend/src/app/reports/dashboard-data-integrity/page.tsx`
- **Route**: `/reports/dashboard-data-integrity`
- **Features**:
  - Run metadata display
  - Summary statistics
  - Findings table with inconsistencies
  - Cursor prompt with copy button
  - Re-run instructions

### 4. Monitoring Panel Integration
- **File**: `frontend/src/app/components/MonitoringPanel.tsx`
- **Change**: "View Reports" button now links to dashboard report page
- **Secondary**: GitHub Actions link available as secondary option

## Report JSON Schema

```json
{
  "run": {
    "workflow": "Dashboard Data Integrity",
    "run_id": "...",
    "created_at": "...",
    "commit": "...",
    "branch": "...",
    "status": "PASS|FAIL"
  },
  "summary": {
    "inconsistencies_total": 0,
    "blockers": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  },
  "inconsistencies": [
    {
      "id": "DI-001",
      "severity": "high|medium|low",
      "entity": "watchlist|trade|portfolio|alerts",
      "symbol": "BTC_USD",
      "field": "trade_enabled",
      "dashboard_value": "...",
      "backend_value": "...",
      "source": {
        "api": "/api/watchlist",
        "backend_module": "app/api/routes_dashboard",
        "db": "table.column"
      },
      "notes": "..."
    }
  ],
  "cursor_prompt": "Generated prompt text..."
}
```

## Environment Variables

### GitHub Actions Secrets (Optional)
- `BACKEND_URL`: Backend URL for posting reports (default: `https://dashboard.hilovivo.com`)
- `REPORT_SECRET`: Secret for authenticating report POST requests (default: `dashboard-data-integrity-secret-2024`)

### Backend Environment Variables
- `REPORT_SECRET`: Secret for validating report POST requests (default: `dashboard-data-integrity-secret-2024`)

## Usage

### Viewing Reports
1. Navigate to Dashboard → Monitoring tab
2. Find "Dashboard Data Integrity" workflow row
3. Click "View Report" button
4. Report page displays latest results

### Re-running Checks
- Push changes to `frontend/**` files
- Or manually trigger workflow from GitHub Actions
- Report automatically updates after workflow completes

### Cursor Prompt
- Click "Copy Prompt" button on report page
- Paste into Cursor to get fix instructions
- Prompt includes all inconsistencies and requirements

## Security

- Reports are protected by `X-Report-Secret` header
- Default secret: `dashboard-data-integrity-secret-2024`
- Change secret in production via environment variables

## Future Enhancements

- Database storage instead of in-memory cache
- Historical report viewing
- Email notifications on failures
- Integration with monitoring alerts

