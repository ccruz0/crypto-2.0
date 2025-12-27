# Price Threshold E2E Test Execution Guide

## Quick Start

```bash
# 1. Start Docker Desktop (if not running)

# 2. Start local stack
cd /Users/carloscruz/automated-trading-platform
./dev_local.sh

# 3. Wait for services (verify they're running)
curl http://localhost:3000  # Should return HTML
curl http://localhost:8000/health  # Should return JSON

# 4. Run the test
cd frontend
ENABLE_TEST_PRICE_INJECTION=1 npx playwright test tests/e2e/price-threshold-e2e.spec.ts
```

## What the Test Does

### Phase 1: UI Threshold Changes
1. Navigates to **Signal Configuration** tab
2. Finds a coin with active BUY/SELL alerts
3. Changes threshold from **10% to 11%** → verifies UI updates
4. Changes threshold to **3%** → verifies UI updates  
5. Sets threshold to **0% ("no limit")** → verifies UI updates

### Phase 2: Price Injection Testing (if `ENABLE_TEST_PRICE_INJECTION=1`)
1. Sets threshold to **10%**
2. Injects price with **10.5% change** → should **PASS** 10% threshold
3. Changes threshold to **11%**
4. Injects price with **11.2% change** → should **PASS** 11% threshold

### Phase 3: Monitoring Verification
1. Navigates to **Monitoring** tab
2. Verifies **Telegram Messages** panel is visible
3. Checks for messages related to test coin
4. Verifies **SENT/BLOCKED** status is displayed correctly

## Expected Test Results

### ✅ Success Criteria
- All threshold changes are saved and reflected in UI
- Price injection successfully triggers signal evaluation
- Monitoring tab shows messages with correct SENT/BLOCKED status
- All critical steps pass

### ❌ Common Issues

**Issue**: "No watchlist rows found"
- **Solution**: Ensure database has watchlist items with active alerts

**Issue**: "Price change threshold input not found"
- **Solution**: Verify Signal Configuration tab is accessible and modal is open

**Issue**: "Test price injection is disabled"
- **Solution**: Set `ENABLE_TEST_PRICE_INJECTION=1` environment variable

**Issue**: "Monitoring tab not found"
- **Solution**: Verify Monitoring tab exists in the UI

## Debugging

### View Backend Logs
```bash
docker compose --profile local logs -f backend
```

Look for logs with `[EVAL_` prefix to trace signal evaluations:
```
[EVAL_abc12345] BTC_USDT evaluation started | strategy=Swing/Conservative | min_price_change_pct=10.0%
[EVAL_abc12345] BTC_USDT BUY signal evaluation | decision=ACCEPT | price_change_pct=10.5% | threshold=10.0%
[EVAL_abc12345] BTC_USDT BUY Telegram send SUCCESS | message_id=12345
```

### View Test Output
The test prints detailed console logs:
- `✅ Found test coin: BTC_USDT (BUY: true, SELL: false)`
- `✅ Threshold changed to $11`
- `✅ Price injected: 50000.00 -> 55250.00 (10.5%)`
- `✅ Monitoring tab accessible`

### Manual Price Injection
You can manually test price injection:
```bash
curl -X POST http://localhost:8000/api/test/inject-price \
  -H "Content-Type: application/json" \
  -d '{
    "symbol": "BTC_USDT",
    "price": 55000.0,
    "rsi": 30.0,
    "ma50": 50000.0,
    "ema10": 50500.0,
    "ma200": 48000.0
  }'
```

## Test Configuration

### Environment Variables
- `ENABLE_TEST_PRICE_INJECTION=1` - Enables test price injection endpoint
- `DASHBOARD_URL=http://localhost:3000` - Frontend URL (default)
- `BASE_URL=http://localhost:3000` - Alternative frontend URL

### Test Timeout
Default Playwright timeout: 30 seconds per step
- Can be adjusted in `playwright.config.ts`

## Next Steps After Test Passes

1. **Review logs** - Check backend logs for structured logging output
2. **Verify Monitoring tab** - Manually check Monitoring tab shows correct SENT/BLOCKED messages
3. **Check Telegram** - Verify Telegram alerts were sent (if configured)
4. **Deploy to AWS** - Once local tests pass, deploy and verify on AWS
5. **Update audit report** - Document results in `docs/monitoring/price_threshold_e2e_audit.md`

## Troubleshooting

### Services Not Starting
```bash
# Check Docker status
docker info

# Check service logs
docker compose --profile local logs backend
docker compose --profile local logs frontend
docker compose --profile local logs db
```

### Test Fails on Price Injection
1. Verify `ENABLE_TEST_PRICE_INJECTION=1` is set
2. Check backend logs for endpoint errors
3. Verify symbol exists in database
4. Check MarketPrice table has data for the symbol

### Test Fails on UI Interaction
1. Take screenshot: `await page.screenshot({ path: 'debug.png' })`
2. Check browser console for errors
3. Verify UI elements are visible (add `await page.waitForTimeout(2000)`)

## Support

For issues or questions:
1. Check backend logs for `[EVAL_` prefixed logs
2. Review test output console logs
3. Verify all prerequisites are met (Docker, services running)
4. Check `README.md` for general setup instructions

