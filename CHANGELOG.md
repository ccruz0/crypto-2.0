# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.40.0] - 2025-11-07

### Added
- Added timing middleware to measure request latency
- Added `/ping_fast` endpoint for minimal response testing
- Added detailed performance logging throughout the application
- Added debug flags for conditional service startup
- Added volume ratio calculation to signals endpoint
- Added comprehensive error handling in database session management

### Fixed
- **Performance**: Fixed `/api/dashboard/state` endpoint taking over 2 minutes
  - Optimized database queries with proper limits (50 recent open orders)
  - Added statement_timeout to prevent hanging queries
  - Reduced exchange_sync page_size from 200 to 50
  - Added 15-second delay to exchange_sync startup to allow initial requests
  - Result: Endpoint now responds in <1 second
- **Telegram Alerts**: Fixed Telegram Notifier not sending alerts
  - Corrected `os.getenv()` to properly use default values when env vars are empty strings
  - Telegram now correctly sends buy signals and alerts
- **Telegram /watchlist Command**: Fixed command showing "No coins with Trade=YES"
  - Changed query to show only coins with `trade_enabled=True` (not all coins)
  - Added status indicators (✅ Trade, 🔔 Alert)
  - Fixed field name from `last_price` to `price`
- **SL/TP Values**: Fixed SL/TP showing "Calculating..." in frontend
  - Ensured `res_up`, `res_down`, `current_price`, `resistance_up`, `resistance_down` always have valid values
  - Added default calculated values if missing from database
  - Fixed `signal_writer.py` syntax errors
  - Forced `market-updater` to use PostgreSQL instead of SQLite
- **Volume Figures**: Fixed volume changing very fast in frontend
  - Changed from `random.uniform()` to deterministic hash-based calculation
  - Ensured `volume_ratio` is always calculated and included
- **ALERT Button**: Fixed network error when pressing ALERT button
  - Corrected `get_db()` generator to re-raise exceptions instead of yielding None
  - Simplified `simulate_alert` endpoint to avoid asyncio event loop conflicts
  - Forced PostgreSQL usage in backend service
- **ETH_USDT Trade Status**: Fixed `trade_enabled` disappearing on dashboard refresh
  - Improved logging in `update_dashboard_item()` to preserve existing values
  - Restored ETH_USDT to `trade_enabled=True`
- **Duplicate Watchlist Items**: Cleaned up duplicate ETH_USDT entries in database

### Changed
- **Docker Compose**: Refactored to use `local` and `aws` profiles
  - Local profile: backend on port 8002, no gluetun dependency
  - AWS profile: backend uses gluetun for outbound traffic
  - Forced `DATABASE_URL` to ensure PostgreSQL usage
- **Database**: All services now explicitly use PostgreSQL (no SQLite fallback)
- **Performance Optimizations**:
  - Exchange sync service now starts with 15s delay
  - Reduced page size for order history sync
  - Optimized dashboard queries with proper limits
  - Improved background service scheduling
- **Logging**: Enhanced logging throughout the application
  - Changed verbose warnings to debug level
  - Added performance timing logs
  - Improved error context and stack traces

### Technical Debt
- Identified inconsistency in open orders between `/api/orders/open` (queries SQLite + PostgreSQL) and `/api/dashboard/state` (queries only PostgreSQL)
- Old order `OPEN0004` from Oct 26 still showing as ACTIVE in SQLite

### Documentation
- Created performance investigation log (`perf_investigation_log.md`)
- Created fix summaries for each issue
- Added inline comments explaining optimizations

## [1.0.0] - Previous Version

Initial stable release.

