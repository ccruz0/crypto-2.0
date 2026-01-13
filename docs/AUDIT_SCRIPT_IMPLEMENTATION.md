# Audit Script Implementation Summary

## Overview

A comprehensive audit script has been created to diagnose why NO Telegram alerts and NO buy/sell orders have been sent for days.

## Files Created

1. **`backend/scripts/audit_no_alerts_no_trades.py`** - Main audit script
2. **`docs/reports/no-alerts-no-trades-audit.md`** - Generated report (created when script runs)

## Script Features

### Global Health Checks

1. **Scheduler Health**
   - Checks if SignalMonitorService is running
   - Verifies last cycle timestamp
   - Detects stalled cycles (no activity in 2x monitor_interval)

2. **Telegram Health**
   - Verifies bot token and chat ID are present
   - Checks if Telegram is enabled (ENVIRONMENT=aws)
   - Finds last successful send timestamp
   - Detects recent errors

3. **Market Data Freshness**
   - Checks last price update timestamp per symbol
   - Detects stale prices (>30 minutes old)
   - Identifies symbols missing price data

4. **Throttle System Sanity**
   - Counts throttled symbols
   - Detects stuck throttle entries (older than 2x cooldown but still blocking)

5. **Trade System Sanity**
   - Checks max open orders threshold vs current open orders
   - Identifies symbols at limit
   - Verifies trade guardrails

### Per-Symbol Analysis

For each watchlist item with `alert_enabled` or `trade_enabled`:

- **Config State**: alert_enabled, trade_enabled, trade_amount_usd, buy_alert_enabled, sell_alert_enabled
- **Market Data**: Current price, last price update time
- **Signal State**: Buy/sell signals, strategy_id, strategy_key
- **ALERT Decision**: EXEC or SKIP with exact reason code
- **PRICE_MOVE Decision**: EXEC or SKIP with exact reason code
- **TRADE Decision**: EXEC or SKIP with exact reason code
- **Blocking Reasons**: Explicit evidence (timestamps, cooldown remaining, thresholds, counts)

### Canonical Reason Codes

- `SKIP_NO_SIGNAL` - No buy/sell signal detected
- `SKIP_ALERT_DISABLED` - alert_enabled=False
- `SKIP_TRADE_DISABLED` - trade_enabled=False
- `SKIP_INVALID_TRADE_AMOUNT` - trade_amount_usd is None or <= 0
- `SKIP_COOLDOWN_ACTIVE` - Throttle cooldown active (includes seconds remaining)
- `SKIP_MAX_OPEN_ORDERS` - Maximum open orders limit reached
- `SKIP_RECENT_ORDER_COOLDOWN` - Recent order cooldown active
- `SKIP_TELEGRAM_FAILURE` - Telegram send failed (includes last error)
- `SKIP_MARKET_DATA_STALE` - Market data older than 30 minutes
- `SKIP_SCHEDULER_NOT_RUNNING` - SignalMonitorService not running
- `SKIP_CONFIG_NOT_APPLIED` - Configuration not applied
- `EXEC_ALERT_SENT` - Alert would be sent
- `EXEC_ORDER_PLACED` - Order would be placed

## Usage

```bash
# Run audit for all symbols (last 168 hours = 7 days)
python backend/scripts/audit_no_alerts_no_trades.py

# Run audit for specific symbols
python backend/scripts/audit_no_alerts_no_trades.py --symbols ETH_USDT,BTC_USD

# Run audit for last 24 hours
python backend/scripts/audit_no_alerts_no_trades.py --since-hours 24

# Specify output file
python backend/scripts/audit_no_alerts_no_trades.py --output docs/reports/my-audit.md
```

## Output

The script generates:

1. **Console Output**: Summary with global status and top root causes
2. **Markdown Report**: Detailed report with:
   - Global status (PASS/FAIL)
   - Global health checks with evidence
   - Per-symbol analysis table
   - Root causes ranked by frequency
   - Recommended fixes with file/line references

## Next Steps

1. **Run the audit script** against the current system:
   ```bash
   python backend/scripts/audit_no_alerts_no_trades.py
   ```

2. **Review the generated report** at `docs/reports/no-alerts-no-trades-audit.md`

3. **Implement minimal fixes** based on the audit findings:
   - Only fix confirmed root causes
   - Add explicit logging when global blockers occur
   - Add heartbeat logs to prove loop is alive
   - Never spam Telegram (respect cooldowns)

4. **Add regression tests** for auditor reason codes (Part D requirement)

## Implementation Notes

- Script runs in "dry" mode by default (no side effects)
- Can run locally or in AWS containers
- Uses existing diagnostic infrastructure (DIAG_* / decision traces / throttle logic)
- Does not refactor unrelated code
- Builds on existing diagnostic tools

## Known Limitations

- Throttle logic is reimplemented in the audit script (should ideally use `should_emit_signal` from signal_throttle.py)
- Some checks may require database access (script handles errors gracefully)
- Telegram message history requires `TelegramMessage` table to exist

## Testing

To test the script:

```bash
# Test help
python backend/scripts/audit_no_alerts_no_trades.py --help

# Test with minimal symbols (if database is available)
python backend/scripts/audit_no_alerts_no_trades.py --symbols ETH_USDT --since-hours 1
```





