# Alert System Smoke Test Instructions

## Overview

This document provides instructions for running the complete smoke test of the alert system.

## Prerequisites

1. Docker services must be running:
   ```bash
   docker compose ps
   ```

2. Backend service must be accessible at `http://localhost:8000`

## Running the Tests

### Task 1-3, 6: Main Smoke Test

Run the main smoke test script inside the Docker backend container:

```bash
docker compose exec backend python scripts/smoke_test_alerts.py
```

This will:
- ✅ Validate DB state (watchlist duplicates)
- ✅ Test backend toggle flow (PUT /api/dashboard/{item_id})
- ✅ Validate Monitoring table (last 50 entries)
- ✅ Test frontend integration (GET /api/dashboard)
- 📄 Generate report in `docs/monitoring/SMOKE_TEST_REPORT_YYYYMMDD.md`

### Task 4: Price Simulation Test

Run the price simulation script separately:

```bash
docker compose exec backend python scripts/simulate_price_test.py
```

This will:
- Fetch a pair from DB
- Simulate price below threshold (BUY)
- Simulate price above threshold (SELL)
- Run signal evaluation directly
- Print generated signal payloads

### Task 5: Validate Monitoring After Simulation

After running the price simulation, check the Monitoring table:

```bash
docker compose exec backend python -c "
from app.database import SessionLocal
from app.models.telegram_message import TelegramMessage
from datetime import datetime, timezone, timedelta

db = SessionLocal()
recent = db.query(TelegramMessage).filter(
    TelegramMessage.timestamp >= datetime.now(timezone.utc) - timedelta(minutes=10)
).order_by(TelegramMessage.timestamp.desc()).limit(10).all()

print(f'Recent messages: {len(recent)}')
for msg in recent:
    print(f'  {msg.timestamp}: {msg.symbol} - {\"BLOCKED\" if msg.blocked else \"SENT\"} - {msg.message[:60]}...')
"
```

## Expected Results

### Task 1: DB State
- ✅ 33 total items
- ✅ 33 unique symbol_currency pairs
- ✅ No duplicates found
- ✅ Sorted list of pairs printed

### Task 2: Toggle Flow
- ✅ PUT requests succeed
- ✅ DB rows updated correctly
- ✅ Monitoring receives events (if implemented)
- ✅ Events NOT marked as blocked

### Task 3: Monitoring Table
- ✅ Last 50 entries retrieved
- ✅ Types: BUY_TOGGLE, SELL_TOGGLE, BUY_SIGNAL, SELL_SIGNAL
- ✅ blocked == false for all
- ✅ message not empty for all

### Task 4: Price Simulation
- ✅ Pair fetched from DB
- ✅ BUY signal generated (price below threshold)
- ✅ SELL signal generated (price above threshold)
- ✅ Signal payloads printed

### Task 5: Monitoring After Simulation
- ✅ 2 new entries in Monitoring (1 BUY, 1 SELL)
- ✅ NOT flagged as blocked

### Task 6: Frontend Integration
- ✅ GET /api/dashboard responds
- ✅ No duplicates in response
- ✅ Correct number of items (33)
- ✅ Values match DB exactly

## Report Generation

The smoke test automatically generates:
- `docs/monitoring/SMOKE_TEST_REPORT_YYYYMMDD.md` - Markdown report
- `docs/monitoring/SMOKE_TEST_REPORT_YYYYMMDD.json` - JSON data

## Troubleshooting

### Database Connection Error
If you see connection errors, ensure Docker services are running:
```bash
docker compose up -d
```

### API Connection Error
If API calls fail, check backend is running:
```bash
docker compose logs backend | tail -20
```

### No Monitoring Events
If toggle events don't appear in monitoring:
- Check if signal_monitor service is running
- Verify alert_enabled is True for test items
- Check logs: `docker compose logs backend | grep -i toggle`

## Notes

- All tests run in DRY RUN mode (no real orders sent)
- Toggle tests restore initial state after testing
- Price simulation uses actual market data from DB
- Monitoring table = telegram_messages table
