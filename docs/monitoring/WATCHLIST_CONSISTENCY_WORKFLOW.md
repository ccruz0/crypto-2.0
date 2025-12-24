# Watchlist Consistency Workflow

**Purpose:** Verify that Watchlist dashboard API values (via `/api/dashboard`) match database records (`WatchlistItem`) for all coins.

**Status:** ✅ Ready for use

---

## Overview

This workflow performs a daily consistency check that compares watchlist values between:

1. **API/Dashboard Layer**: JSON returned by `/api/dashboard` (what the frontend shows)
2. **Database Layer**: `WatchlistItem` records in the database (backend source of truth)

The check validates:
- **Flags**: `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`, `trade_enabled`
- **Trading Settings**: `trade_amount_usd`, `sl_tp_mode`
- **Consistency**: Ensures symbols exist in both API and database
- **Internal Logic**: Validates that alert flags are logically consistent (e.g., if buy/sell alerts are enabled, master alert should be enabled)

---

## Classification Types

The workflow classifies each field comparison as:

- **EXACT_MATCH**: Values are identical (or within tolerance for numeric fields)
- **NUMERIC_DRIFT**: Numeric values differ slightly but within acceptable tolerance (0.1% relative or 1e-6 absolute)
- **MISMATCH**: Values differ significantly or are incompatible (e.g., boolean mismatch, None vs value)

---

## Manual Execution

### From Local Machine

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/watchlist_consistency_remote.sh
```

This will:
1. SSH to AWS server
2. Execute the consistency check inside the backend container
3. Generate a Markdown report under `docs/monitoring/`
4. Print the report path

### Directly on AWS Server

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
docker compose exec -T backend-aws python scripts/watchlist_consistency_check.py
```

---

## Reading the Report

Reports are generated daily at:
- `docs/monitoring/watchlist_consistency_report_YYYYMMDD.md` (dated report)
- `docs/monitoring/watchlist_consistency_report_latest.md` (always points to latest)

### Report Structure

1. **Summary Section**:
   - Total number of symbols in database
   - API availability status
   - Count of enabled flags (trade, alerts, etc.)
   - API vs Database comparison statistics:
     - Number of API mismatches
     - Symbols only in database
     - Symbols only in API

2. **Issues Section**:
   - List of all issues found, grouped by symbol
   - Each issue describes the specific problem (e.g., "trade_enabled: DB=True, API=False")

3. **Watchlist Items Table**:
   - For each symbol, shows:
     - Symbol name
     - Trade, Alert, Buy Alert, Sell Alert status (✅/❌)
     - Throttle state (✅/—)
     - Whether symbol exists in API (✅/❌)
     - List of issues found for that symbol

### Example Report Entry

```markdown
## Summary
- **Total Items (DB):** 33
- **API Available:** ✅ Yes
- **API Mismatches:** 2
- **Only in DB:** 1
- **Only in API:** 0

## ⚠️ Issues Found
- **ETH_USDT**: trade_enabled: DB=True, API=False
- **BTC_USDT**: Symbol exists in DB but not in API response

## Watchlist Items
| Symbol | Trade | Alert | Buy Alert | Sell Alert | Throttle | In API | Issues |
|--------|-------|-------|-----------|------------|----------|--------|--------|
| ETH_USDT | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | trade_enabled: DB=True, API=False |
| BTC_USDT | ❌ | ✅ | ✅ | ✅ | ✅ | ❌ | Symbol exists in DB but not in API response |
```

---

## What to Investigate

### When a Symbol Has Issues

1. **API vs Database Mismatches**:
   - **Field differences**: If a field like `trade_enabled`, `alert_enabled`, etc. differs between API and DB
     - Check if the API endpoint is using cached data
     - Verify that database updates are being properly reflected in the API response
     - Check if there's a sync issue between `WatchlistItem` and `WatchlistMaster` tables

2. **Symbol exists in DB but not in API**:
   - The symbol may be filtered out by the API endpoint (e.g., `is_deleted=True`)
   - Check if the API endpoint has different filtering logic
   - Verify the symbol is not soft-deleted

3. **Symbol exists in API but not in DB**:
   - The API may be returning data from a different source (e.g., `WatchlistMaster` table)
   - Check if there's a sync issue between tables
   - Verify database integrity

4. **Internal Consistency Issues**:
   - **alert_enabled=True but both buy/sell alerts are False**: Master alert is enabled but no specific alerts are enabled
   - **buy/sell alert enabled but master alert_enabled=False**: Specific alerts are enabled but master switch is off
   - These indicate logical inconsistencies that should be fixed

5. **Action items**:
   - If API differs from DB: Check API endpoint logic and caching
   - If symbol missing in one source: Check filtering and sync logic
   - If flags are inconsistent: Fix the logical inconsistency in the database

---

## Scheduling at 03:00 Every Day

To run the consistency check automatically every night at 03:00 server time, add this to the server's crontab:

```bash
# Edit crontab
crontab -e

# Add this line:
0 3 * * * cd /home/ubuntu/automated-trading-platform && docker compose exec -T backend-aws python scripts/watchlist_consistency_check.py >> /home/ubuntu/watchlist_consistency_cron.log 2>&1
```

This will:
- Run at 03:00 every day
- Execute the consistency check
- Append output to `/home/ubuntu/watchlist_consistency_cron.log`
- Generate reports in `docs/monitoring/`

### Viewing Cron Logs

```bash
ssh hilovivo-aws
tail -f /home/ubuntu/watchlist_consistency_cron.log
```

---

## Telegram Notifications

If there are symbols with issues (API mismatches, missing symbols, or internal inconsistencies), the script will automatically send a summary to Telegram (if the Telegram service is configured).

The message includes:
- Total symbols checked
- Number of API mismatches
- Number of symbols only in DB or only in API
- Link to the report

---

## Technical Details

### Comparison Logic

- **Numeric fields**: Uses relative tolerance (0.1%) and absolute tolerance (1e-6) for float comparisons
- **Boolean fields**: Exact match required
- **String fields**: Case-insensitive comparison after normalization
- **None values**: Treated as distinct from other values (DB=None vs API=value is a mismatch)

### Data Sources

1. **Database**: Direct query of `WatchlistItem` table (filtered by `is_deleted=False`)
2. **API**: HTTP GET to `/api/dashboard` endpoint (from inside container or via environment variable `API_URL`)

The script automatically detects the API URL by trying common ports (8002, 8000) when running inside Docker, or uses the `API_URL` environment variable if set.

### Fields Compared

**Boolean Flags:**
- `trade_enabled`
- `alert_enabled` (master alert switch)
- `buy_alert_enabled`
- `sell_alert_enabled`

**Trading Settings:**
- `trade_amount_usd` (numeric)
- `sl_tp_mode` (string: "conservative" or "aggressive")

### Internal Consistency Checks

The script also validates logical consistency:
- If `alert_enabled=True`, at least one of `buy_alert_enabled` or `sell_alert_enabled` should be `True`
- If `buy_alert_enabled=True` or `sell_alert_enabled=True`, then `alert_enabled` should be `True`

---

## Troubleshooting

### Script Fails to Run

1. **Check container is running**:
   ```bash
   docker compose ps backend-aws
   ```

2. **Check Python path**:
   ```bash
   docker compose exec backend-aws python -c "import sys; print(sys.path)"
   ```

3. **Check imports**:
   ```bash
   docker compose exec backend-aws python -c "from app.services.signal_evaluator import evaluate_signal_for_symbol; print('OK')"
   ```

### API Endpoint Not Available

The script tries ports 8000 and 8002. If both fail:
- Check if the backend API is running
- Verify the port in `docker-compose.yml`
- The script will continue with empty API data (DB and computed comparisons will still work)

### Report Not Generated

- Check write permissions on `docs/monitoring/` directory
- Verify disk space on the server
- Check logs for errors

---

## Related Documentation

- **Signal Evaluation Unification**: `docs/monitoring/SIGNAL_EVALUATION_UNIFICATION.md`
- **Watchlist Audit Workflow**: `docs/WORKFLOW_WATCHLIST_AUDIT.md`
- **Signal Flow Overview**: `docs/monitoring/signal_flow_overview.md`

---

## Maintenance

This workflow is **read-only** and does not modify any trading logic or live monitoring behavior. It is purely diagnostic.

If you need to update the fields being compared or the tolerance values, edit:
- `backend/scripts/watchlist_consistency_check.py`
- Constants: `NUMERIC_FIELDS`, `BOOLEAN_FIELDS`, `STRING_FIELDS`
- Tolerance: `REL_TOL`, `ABS_TOL`

