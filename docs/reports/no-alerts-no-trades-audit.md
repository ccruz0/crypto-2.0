# No Alerts / No Trades Audit Report

**Generated:** 2026-01-01T10:41:39.777334+00:00
**Since Hours:** 1

## GLOBAL STATUS

**❌ FAIL**

### Global Health Checks

#### ❌ SCHEDULER

- **Running:** False
- **Last Cycle:** None
- **Stalled:** False

**Evidence:**
- SignalMonitorService.is_running = False
- No last_run_at timestamp found
- TradingScheduler.running = False

#### ❌ TELEGRAM

- **Enabled:** False
- **Bot Token:** ❌
- **Chat ID:** ❌
- **Last Send:** None

**Evidence:**
- TELEGRAM_BOT_TOKEN not set
- TELEGRAM_CHAT_ID_AWS not set (or ENVIRONMENT != aws)
- Telegram notifier disabled (ENVIRONMENT != aws or missing credentials)
- ENVIRONMENT= (must be 'aws' for Telegram)

#### ❌ MARKET_DATA

- **Stale Symbols:** 0
- **Missing Symbols:** 0

**Evidence:**
- Error checking market data: (psycopg2.OperationalError) connection to server at "172.19.0.3", port 5432 failed: timeout expired

(Background on this error at: https://sqlalche.me/e/20/e3q8)

#### ❌ THROTTLE

- **Throttled Count:** 0
- **Stuck Entries:** 0

**Evidence:**
- Error checking throttles: (psycopg2.OperationalError) connection to server at "172.19.0.3", port 5432 failed: timeout expired

(Background on this error at: https://sqlalche.me/e/20/e3q8)

#### ❌ TRADE_SYSTEM

- **Total Open Orders:** 0
- **Max Per Symbol:** 3
- **Symbols At Limit:** 0

**Evidence:**
- Error checking trade system: (psycopg2.OperationalError) connection to server at "172.19.0.3", port 5432 failed: timeout expired

(Background on this error at: https://sqlalche.me/e/20/e3q8)

## PER-SYMBOL ANALYSIS

| Symbol | Alert Enabled | Trade Enabled | Price | Signal | Alert Decision | Alert Reason | Trade Decision | Trade Reason |
|--------|--------------|---------------|-------|--------|----------------|--------------|----------------|--------------|
| ERROR | ❌ | ❌ | N/A | NONE | SKIP | ERROR | SKIP | ERROR |

## ROOT CAUSES

Ranked by frequency:

1. **ERROR** - 2 occurrences

## RECOMMENDED FIXES

### Scheduler not running

- **Fix:** Start SignalMonitorService via API endpoint or restart backend service
- **File:** backend/app/main.py
- **Line:** 277

### Telegram notifier disabled

- **Fix:** Set ENVIRONMENT=aws and ensure TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID_AWS are set
- **File:** docker-compose.yml or environment variables
- **Line:** N/A

### Market data stale

- **Fix:** Check market_updater.py is running and can reach external APIs
- **File:** backend/market_updater.py
- **Line:** 328

### 1 symbols have alert_enabled=False

- **Fix:** Enable alerts in dashboard for symbols that should receive alerts
- **File:** Dashboard UI
- **Line:** N/A

### 1 symbols have no buy/sell signals

- **Fix:** Check signal calculation logic and market conditions
- **File:** backend/app/api/routes_signals.py
- **Line:** N/A
