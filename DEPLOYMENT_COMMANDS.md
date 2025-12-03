# Deployment Commands for Live Alert Monitor Fix

## From Your Mac Terminal

### 1. Deploy to AWS

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && git pull && docker compose build --no-cache backend-aws && docker compose up -d backend-aws'
```

### 2. Verify Backend Health

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose ps backend-aws'
```

Should show: `Up (healthy)`

### 3. Run Debug Script (Check Current Signals)

```bash
cd /Users/carloscruz/automated-trading-platform
ssh hilovivo-aws 'cd /home/ubuntu/automated-trading-platform && docker compose exec backend-aws bash -c "cd /app && python scripts/debug_live_signals_all.py"'
```

Look for:
- `BUY_SIGNALS_NOW: [...]`
- `SELL_SIGNALS_NOW: [...]`
- `Symbols that can emit SELL alert: N`

### 4. Monitor Live Logs

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 0 | grep -E "LIVE_ALERT_DECISION|LIVE_BUY_CALL|LIVE_SELL_CALL|LIVE_BUY_SKIPPED|LIVE_SELL_SKIPPED|ALERT_EMIT_FINAL"
```

### 5. Check Specific Symbol

```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 500 | grep "ALGO_USDT" | grep -E "LIVE_ALERT_DECISION|LIVE_SELL|ALERT_EMIT"
```

## Testing Commands

### Run Unit Tests (if available)

```bash
cd /Users/carloscruz/automated-trading-platform
python3 -m pytest backend/tests/test_signal_monitor.py -v 2>&1 | head -50
```

### Type Check (if using mypy)

```bash
cd /Users/carloscruz/automated-trading-platform
python3 -m mypy backend/app/services/signal_monitor.py --ignore-missing-imports 2>&1 | head -30
```

