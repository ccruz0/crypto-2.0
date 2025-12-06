# Version 0.40.0 Release Summary

**Release Date:** November 7, 2025
**Previous Version:** 1.0.0

## Overview
This release focuses on **performance optimization**, **bug fixes**, and **improved reliability** of the Automated Trading Platform. The most significant improvement is the dashboard endpoint optimization, reducing response time from over 2 minutes to under 1 second.

## Major Improvements

### 🚀 Performance Enhancements
- **Dashboard Endpoint**: Reduced `/api/dashboard/state` response time from 2+ minutes to <1 second
  - Optimized database queries with proper limits
  - Added statement timeouts to prevent hanging queries
  - Improved background service scheduling
  - Added request timing middleware

### 🔧 Bug Fixes
1. **Telegram Alerts** - Fixed Notifier not sending messages due to empty environment variables
2. **Telegram /watchlist Command** - Now correctly shows only coins with Trade=YES
3. **SL/TP Values** - Fixed "Calculating..." showing indefinitely in frontend
4. **Volume Figures** - Fixed rapidly changing volume values (now deterministic)
5. **ALERT Button** - Fixed network error when pressing the alert button
6. **ETH_USDT Status** - Fixed trade_enabled disappearing on dashboard refresh
7. **Database Session** - Fixed `get_db()` generator error handling

### 📦 Infrastructure
- **Docker Compose**: Refactored with `local` and `aws` profiles for better environment separation
- **Database**: Forced all services to use PostgreSQL (removed SQLite fallback)
- **Logging**: Enhanced logging with better context and debug levels

## Files Modified

### Backend
- `backend/app/main.py` - Version bump, timing middleware, debug flags
- `backend/app/api/routes_dashboard.py` - Query optimizations, logging improvements
- `backend/app/api/routes_signals.py` - Fixed SL/TP calculations, deterministic volumes
- `backend/app/api/routes_test.py` - Simplified alert endpoint
- `backend/app/database.py` - Fixed generator exception handling
- `backend/app/services/telegram_notifier.py` - Fixed env var handling
- `backend/app/services/telegram_commands.py` - Fixed /watchlist command
- `backend/app/services/exchange_sync.py` - Optimized sync intervals and delays
- `backend/app/services/signal_writer.py` - Fixed syntax errors
- `backend/market_updater.py` - Added signal sync, forced PostgreSQL

### Frontend
- `frontend/package.json` - Version bump to 0.40.0
- `frontend/next.config.ts` - Build optimizations
- `frontend/src/lib/api.ts` - Type fixes

### Infrastructure
- `docker-compose.yml` - Profile refactoring, port configurations, forced PostgreSQL

## Documentation Added
- `CHANGELOG.md` - Complete changelog
- `backend/PERFORMANCE_FIX_SUMMARY.md` - Performance fix details
- `backend/TELEGRAM_ALERT_FIX.md` - Telegram alert fix
- `backend/WATCHLIST_COMMAND_FIX.md` - Watchlist command fix
- `backend/SL_TP_VERIFICATION.md` - SL/TP fix verification
- `backend/VOLUME_FIX_SUMMARY.md` - Volume fix details
- `backend/ALERT_BUTTON_FIX.md` - Alert button fix
- `backend/ETH_TRADE_ENABLED_FIX.md` - ETH trade status fix
- `backend/OPEN_ORDERS_ISSUE.md` - Open orders inconsistency
- `backend/perf_investigation_log.md` - Performance investigation

## Breaking Changes
None - This release is backward compatible with version 1.0.0

## Known Issues
- Open orders inconsistency between endpoints (SQLite vs PostgreSQL) - Non-critical
- Old order OPEN0004 from Oct 26 still showing as ACTIVE in SQLite - Will be cleaned up

## Upgrade Instructions

### Local Development
```bash
cd /Users/carloscruz/automated-trading-platform
docker compose --profile local down
docker compose --profile local pull
docker compose --profile local up -d db backend frontend
```

### AWS Deployment
```bash
cd /Users/carloscruz/automated-trading-platform
docker compose --profile aws down
docker compose --profile aws pull
docker compose --profile aws up -d
```

## Testing
Before deploying to production:
1. ✅ Test dashboard loads in <1 second
2. ✅ Test Telegram /watchlist command shows correct coins
3. ✅ Test ALERT button sends notifications
4. ✅ Test SL/TP values display correctly
5. ✅ Test volume figures are stable
6. ⏳ Test open orders sync from exchange (pending)

## Next Steps
1. Clean up old SQLite orders
2. Sync real exchange orders to PostgreSQL
3. Add automated cleanup job for stale orders
4. Consider deprecating SQLite completely

## Contributors
- Performance optimization and bug fixes by AI Assistant
- Testing and validation by Carlos Cruz

---

**Thank you for using the Automated Trading Platform!**

