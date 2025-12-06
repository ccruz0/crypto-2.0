# Watchlist Consistency Workflow

**Purpose:** Verify that Watchlist UI values (via `/api/watchlist`) match database records and strategy calculation for all coins.

**Status:** ✅ Ready for use

---

## Overview

This workflow performs a daily consistency check that compares watchlist values across three layers:

1. **API/UI Layer**: JSON returned by `/api/watchlist` (what the frontend shows)
2. **Database Layer**: `WatchlistItem` records in the database
3. **Strategy/Calculation Layer**: Ground truth values computed using the same functions as the live monitor (`evaluate_signal_for_symbol`)

The check validates:
- **Prices**: Current market price
- **Indicators**: RSI, MA50, MA200, EMA10, ATR
- **Targets**: Buy target, take profit, stop loss
- **Strategy**: Strategy profile, risk mode, SL/TP mode
- **Flags**: `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`, `trade_enabled`
- **Other fields**: All fields used by the Watchlist UI

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
   - Total number of symbols checked
   - How many are fully OK
   - How many have minor drift
   - How many have issues

2. **Symbols with Issues Table**:
   - Quick overview of symbols that have mismatches
   - Lists which fields are problematic

3. **Detailed Per-Symbol Section**:
   - For each symbol, a table showing:
     - Field name
     - DB value
     - API value
     - Computed value (from strategy evaluation)
     - Classification (EXACT_MATCH, NUMERIC_DRIFT, MISMATCH)
   - Additional computed strategy info (preset, decision, index, signals)

### Example Report Entry

```markdown
### ETH_USDT

**Status:** OK

| Field | DB | API | Computed | Classification |
|-------|----|-----|----------|----------------|
| price | 3079.1700 | 3079.1700 | 3079.1700 | EXACT_MATCH |
| rsi | 75.50 | 75.50 | 75.50 | EXACT_MATCH |
| alert_enabled | True | True | None | EXACT_MATCH |
| buy_alert_enabled | True | False | None | MISMATCH |
```

---

## What to Investigate

### When a Symbol Has Issues

1. **Check the field classification**:
   - `MISMATCH` on boolean/string fields → Likely a data sync issue
   - `NUMERIC_DRIFT` on prices/indicators → May be normal due to timing differences
   - `MISMATCH` on computed vs DB/API → Strategy evaluation may be using different data source

2. **Common causes**:
   - **API cache stale**: API may be returning cached values while DB has newer data
   - **Computed values different**: Strategy evaluation may be using a different indicator window or data source
   - **Flag mismatches**: `buy_alert_enabled` or `sell_alert_enabled` may have been updated in DB but not reflected in API

3. **Action items**:
   - If API and DB match but computed differs: Check if strategy evaluation is using correct data source
   - If API differs from DB: Check API caching logic
   - If flags differ: Verify watchlist update logic

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

If there are symbols with issues (`MISMATCH` classifications), the script will automatically send a summary to Telegram (if the Telegram service is configured).

The message includes:
- Total symbols checked
- Number of symbols with issues
- Link to the report

---

## Technical Details

### Comparison Logic

- **Numeric fields**: Uses relative tolerance (0.1%) and absolute tolerance (1e-6)
- **Boolean fields**: Exact match required
- **String fields**: Case-insensitive comparison after normalization

### Data Sources

1. **Database**: Direct query of `WatchlistItem` table
2. **API**: HTTP GET to `/api/watchlist` endpoint (from inside container)
3. **Computed**: Uses `evaluate_signal_for_symbol()` which:
   - Fetches market data using the same logic as `SignalMonitorService`
   - Calculates trading signals using `calculate_trading_signals()`
   - Returns ground truth values for price, RSI, MAs, etc.

### Fields Compared

**Numeric:**
- `price`, `rsi`, `ma50`, `ma200`, `ema10`, `atr`
- `buy_target`, `take_profit`, `stop_loss`
- `sl_price`, `tp_price`, `sl_percentage`, `tp_percentage`
- `min_price_change_pct`, `alert_cooldown_minutes`, `trade_amount_usd`

**Boolean:**
- `alert_enabled`, `buy_alert_enabled`, `sell_alert_enabled`
- `trade_enabled`, `trade_on_margin`, `sold`, `is_deleted`
- `skip_sl_tp_reminder`

**String:**
- `sl_tp_mode`, `order_status`, `exchange`

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

