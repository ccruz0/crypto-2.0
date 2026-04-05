# End-to-End Test Suite

This directory contains Playwright-based end-to-end tests for the Trading Dashboard.

## Test Files

- **`dashboard-full-e2e.spec.ts`**: Comprehensive full-stack e2e tests covering:
  - Dashboard loading and initialization
  - Monitoring tab functionality
  - Workflows box and execution
  - Alert flag toggling and synchronization
  - Data persistence and backend sync
  - Runtime error detection (TDZ fixes)

- **`alerts-watchlist.spec.ts`**: Tests for alert flag functionality in watchlist
- **`watchlist-alert-persistence.spec.ts`**: Tests for alert flag persistence
- **`watchlist_audit.spec.ts`**: Watchlist audit tests

## Running Tests

### Run all e2e tests
```bash
cd frontend
npm run test:e2e
```

### Run full e2e test suite
```bash
cd frontend
npm run test:e2e:full
```

### Run in headed mode (see browser)
```bash
cd frontend
npm run test:e2e:full:headed
```

### Run specific test file
```bash
cd frontend
npx playwright test tests/e2e/dashboard-full-e2e.spec.ts
```

## Environment Variables

Tests use the following environment variables (with defaults):

- `DASHBOARD_URL`: Dashboard URL (default: `http://localhost:3000`)
- `API_URL`: Backend API URL (default: `http://localhost:8002/api`)

Set these in your environment or `.env` file:

```bash
export DASHBOARD_URL=http://localhost:3000
export API_URL=http://localhost:8002/api
```

## Test Coverage

### Dashboard Full E2E Test Suite

1. **Dashboard Loading**
   - ✅ Loads without runtime errors
   - ✅ Displays all main tabs
   - ✅ No TDZ (Temporal Dead Zone) errors

2. **Monitoring Tab**
   - ✅ Opens and displays all sections
   - ✅ Shows Monitoring Workflows box
   - ✅ Workflows are visible and executable
   - ✅ Handles execution errors gracefully

3. **Alert Flags**
   - ✅ Toggle alert flags
   - ✅ Persist changes across refresh
   - ✅ Sync from backend on load
   - ✅ Do not overwrite from getTopCoins

4. **Data Synchronization**
   - ✅ Load alert flags from backend
   - ✅ Merge backend and localStorage correctly
   - ✅ Handle network errors gracefully

5. **Portfolio & Watchlist**
   - ✅ Display portfolio data when available
   - ✅ Display watchlist coins
   - ✅ Handle unavailable data gracefully

## Prerequisites

1. **Install Playwright browsers**:
   ```bash
   cd frontend
   npx playwright install
   ```

2. **Start the frontend dev server** (for local testing):
   ```bash
   cd frontend
   npm run dev
   ```

3. **Start the backend** (optional, for full integration):
   ```bash
   # Backend should be running on port 8002
   ```

## Test Execution Notes

- Tests are designed to be resilient to network errors (backend might not be running)
- Tests verify that the dashboard doesn't crash even with API errors
- TDZ (Temporal Dead Zone) tests specifically verify the fix for `isCancelledStatus` ordering
- Alert flag tests verify the new synchronization logic that prevents overwriting from `getTopCoins()`

## Debugging Failed Tests

1. **Run in headed mode** to see what's happening:
   ```bash
   npm run test:e2e:full:headed
   ```

2. **Check screenshots** (automatically saved on failure):
   - Look in `test-results/` directory

3. **View trace** (if enabled):
   ```bash
   npx playwright show-trace trace.zip
   ```

4. **Check console logs** in the test output for detailed error messages

## Continuous Integration

These tests can be integrated into CI/CD pipelines. Ensure:
- Frontend is built: `npm run build`
- Frontend server is started: `npm start`
- Tests run: `npm run test:e2e:full`






