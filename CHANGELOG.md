# Changelog
n


All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

#### Open Orders Detail: BUY-Based Positions Only

- **Fixed**: Open Orders Detail tab now correctly shows BUY orders as base positions
  - Each position row represents a BUY order (baseOrder)
  - SELL orders appear only as childOrders (TP/SL) linked to the BUY via `parent_order_id`
  - SELL-only orders are no longer shown as main positions
  - Main row displays: Symbol, Position Qty (netOpenQuantity), Entry Price (basePrice), Entry Total (baseTotal), Created (baseCreatedAt), TP count, SL count
  - Expanded view shows: BASE BUY order first, then child SELL orders (TP/SL) with their types
  - Backend enforces that `baseSide === 'BUY'` for all positions
  - Frontend validates and filters out any positions with `baseSide !== 'BUY'`

### Added

#### New "Open Orders Detail" Dashboard Tab

- **New Tab**: Added "Open Orders Detail" tab to the dashboard
  - Shows portfolio positions and open orders grouped by symbol
  - Displays position quantity, total open order quantity, and number of orders per symbol
  - Expandable rows to view detailed order information
  - Each order shows: order number, side (BUY/SELL), quantity, price, creation date/time, and TP/SL status
  - TP/SL orders are linked to their parent orders using `parent_order_id` and `order_role` fields
  - Backend endpoint: `/api/dashboard/open-orders-summary` that groups orders by symbol and includes portfolio positions

### Fixed

#### Dashboard State Portfolio Loading and Signals Timeouts

- **Symptom**: 
  - Dashboard showed "No balances in dashboard state, falling back to old endpoint"
  - Portfolio assets array was empty (0 coins)
  - `/signals` endpoint timing out after 15s for BTC_USDT
  - Frontend console showed "XLD NOT found in cleanedCoins! Total coins: 0"
- **Root Cause**: 
  - `/dashboard/state` endpoint was "ultra-simplified" to return empty data immediately, preventing portfolio from loading
  - `/signals` endpoint lacked detailed logging to identify timeout causes
  - Missing portfolio data caused frontend `cleanedCoins` to be empty
- **Fix**: 
  - **Restored `/dashboard/state` endpoint** to load portfolio from `get_portfolio_summary` (v4.0 behavior):
    - Loads balances from `PortfolioBalance` table via portfolio cache
    - Filters balances using v4.0 logic: `balance > 0 OR usd_value > 0` (includes all balances, even if USD value not calculated)
    - Returns proper `portfolio.assets` array with currency, balance, and usd_value
    - Loads open orders with COALESCE for NULL timestamps (v4.0 behavior)
    - Adds detailed logging: number of assets, first 10 symbols, timing information
  - **Enhanced `/signals` endpoint logging**:
    - Added detailed timing logs for database queries, price fetcher calls, and volume fetches
    - Logs when requests start, finish, and any external API calls with durations
    - Warns if calculation takes > 2s, errors if > 15s (frontend timeout)
    - Helps identify slow operations causing timeouts
- **Result**: 
  - Dashboard now loads portfolio balances correctly
  - Portfolio assets array is populated with all balances > 0
  - Signals endpoint has comprehensive logging to diagnose timeout issues
  - Frontend can now process coins without falling back to old endpoint
- **Files Changed**:
  - `backend/app/api/routes_dashboard.py`: Restored proper portfolio loading from portfolio_cache
  - `backend/app/api/routes_signals.py`: Added detailed logging for timeout diagnosis

#### Frontend → Backend URL in Docker

- **Symptom**: Dashboard could not load portfolio/orders because frontend could not reach the backend. Docker logs showed `ECONNREFUSED 127.0.0.1:8000` errors
- **Root Cause**: 
  - Frontend SSR (server-side) was using `http://175.41.189.249:8002/api` (external IP) inside Docker, which is invalid
  - Frontend client-side detection logic was not properly handling Docker vs browser contexts
  - Inside Docker containers, services must communicate using Docker service names (`backend-aws:8002`), not localhost or external IPs
- **Fix**: 
  - Changed `NEXT_PUBLIC_API_URL` in `docker-compose.yml` for `frontend-aws` service from `http://175.41.189.249:8002/api` to `http://backend-aws:8002/api` (using Docker service name and internal port)
  - Updated `frontend/src/lib/environment.ts` to properly handle SSR vs client-side contexts:
    - **SSR (server-side)**: Uses `process.env.NEXT_PUBLIC_API_URL` which is set to `http://backend-aws:8002/api` in Docker
    - **Client-side (browser)**: Uses `localhost:8002/api` when accessing from browser (relies on Docker port mapping), or domain-based URLs for production
  - Added clear comments explaining the difference between server-side (Docker network) and client-side (browser) contexts
- **Result**: 
  - Frontend SSR can now successfully reach the backend from inside Docker using the service name
  - Frontend client-side uses appropriate URLs based on hostname detection
  - Dashboard can now load portfolio and orders data without connection errors
- **Files Changed**:
  - `docker-compose.yml`: Updated `NEXT_PUBLIC_API_URL` environment variable for `frontend-aws` service
  - `frontend/src/lib/environment.ts`: Improved environment detection logic with clear SSR vs client-side handling

#### Dashboard Rollback to v4.0 Behavior

- **Portfolio Loading**: Restored v4.0 portfolio loading logic
  - **Issue**: Portfolio was not loading due to filter that excluded balances with USD value = 0
  - **Fix**: Changed filter from `if usd_value > 0` to `if balance > 0 or usd_value > 0` to include all balances, even if USD value hasn't been calculated yet
  - **Result**: Portfolio now shows all assets with balances > 0, matching v4.0 behavior

- **Open Orders Loading**: Restored v4.0 open orders loading logic
  - **Issue**: Open orders query was using `exchange_create_time.desc()` which excluded orders with NULL `exchange_create_time`
  - **Fix**: Changed to use `COALESCE(exchange_create_time, created_at).desc()` to handle NULL values
  - **Result**: All open orders are now returned, even if `exchange_create_time` is NULL, matching v4.0 behavior

- **Executed Orders Loading**: Restored v4.0 executed orders loading logic
  - **Issue**: Executed orders query was using `exchange_update_time.desc()` which excluded orders with NULL `exchange_update_time`
  - **Fix**: Changed to use `COALESCE(exchange_update_time, updated_at).desc()` to handle NULL values
  - **Result**: All executed orders are now returned, even if `exchange_update_time` is NULL, matching v4.0 behavior

- **Root Cause**: Recent "optimizations" added strict NULL checks that excluded valid data. The v4.0 code used COALESCE to handle NULL values gracefully, ensuring all data was returned.

- **Changes Made**:
  - `backend/app/api/routes_dashboard.py`: Fixed portfolio filter and open orders query
  - `backend/app/api/routes_orders.py`: Fixed open orders and executed orders queries
  - All queries now use COALESCE to handle NULL timestamp fields, matching v4.0 behavior

## [0.40.0] - 2025-11-07

### Executive Summary

Version 4.0 represents a major performance and reliability overhaul of the Automated Trading Platform. The release focuses on eliminating critical bottlenecks, fixing production bugs, and establishing a robust infrastructure foundation. The most significant achievement is reducing the dashboard endpoint response time from over 2 minutes to under 1 second—a **99%+ performance improvement**.

### Architecture Overview

The platform follows a microservices architecture:
- **Nginx** (TLS Reverse Proxy): Terminates TLS, routes `/api/*` → backend:8002, `/` → frontend:3000
- **Frontend** (Next.js): Port 3000, consumes unified `/api` endpoint
- **Backend** (FastAPI): Port 8002, PostgreSQL database, optional Gluetun VPN (AWS profile)
- **Deployment Profiles**: `local` (direct access) and `aws` (VPN routing)

### Added

#### Performance & Monitoring
- Added timing middleware to measure request latency
- Added `/ping_fast` endpoint for minimal response testing
- Added detailed performance logging throughout the application
- Added debug flags for conditional service startup
- Added volume ratio calculation to signals endpoint
- Added comprehensive error handling in database session management

#### Infrastructure & Deployment
- **Unified SSH Helper System** (`scripts/ssh_key.sh`):
  - Centralized SSH/SCP/RSYNC operations through helper functions
  - Single source of truth for SSH configuration
  - Non-interactive operations (no passphrase prompts)
  - Complete removal of `~/.ssh/crypto2` dependency
  - Support for heredoc SSH commands

- **Pre-Deployment Validation System**:
  - `scripts/test_ssh_system.sh` - Strict validator for SSH helper usage
  - `scripts/pre_deploy_check.sh` - Pre-flight validation with DRY_RUN simulations
  - `scripts/simulate_deploy.sh` - End-to-end deployment simulator (zero-risk testing)
  - `scripts/deploy_production.sh` - Production deployment with explicit confirmation
  - All scripts support `DRY_RUN=1` mode for safe testing

- **Deployment Orchestration**:
  - `scripts/start-stack-and-health.sh` - Top-level helper for complete deployment
  - Environment variable configuration (`SERVER`, `REMOTE_PROJECT_DIR`)
  - Clear error messages and comprehensive logging

- **Health Monitoring**:
  - `health_monitor.timer` (systemd) - Monitors backend/frontend endpoints every 5 minutes
  - `dashboard_health_check.timer` (systemd) - Validates dashboard data quality every 15 minutes
  - Telegram alerts on health check failures
  - Installation scripts: `install_health_monitor.sh`, `install_dashboard_health_check.sh`

#### API Improvements
- **Consistent JSON Responses**:
  - All endpoints return JSON, never HTML error pages
  - Success format: `{ ok: true, success: true, ... }`
  - Error format: `{ ok: false, success: false, error: "...", mode: "DRY_RUN" }`
  - Applied to `/trading/live-toggle` and `/trading/live-status`

- **Frontend Response Handling**:
  - Robust response parsing that reads body exactly once
  - Safe JSON parsing with fallback handling
  - Prevents "body stream already read" errors

#### Nginx Configuration
- Exact-match location for `/api/health` (processed before general `/api` block)
- Prevents error-page interception for JSON API responses
- Ensures health checks always reach backend

### Fixed

#### Performance Optimizations

- **Dashboard Endpoint** (`/api/dashboard/state`): Fixed taking over 2 minutes
  - **Root Causes Identified**:
    - Unbounded database queries fetching all historical data
    - Missing query limits on open orders
    - No statement timeouts, allowing queries to hang indefinitely
    - Synchronous exchange API calls blocking request handling
    - Inefficient background service startup blocking HTTP requests
  
  - **Solutions Implemented**:
    - Optimized database queries with proper limits (50 recent open orders)
    - Added statement_timeout to prevent hanging queries (30s timeout)
    - Reduced exchange_sync page_size from 200 to 50
    - Added 15-second delay to exchange_sync startup to allow initial requests
    - Implemented SQL aggregation instead of Python-side calculations
    - Added composite indexes on frequently queried columns
    - Changed from sequential to parallel API calls in frontend
  
  - **Results**:
    - Response time: **2+ minutes → <1 second** (99%+ improvement)
    - Database query time: Reduced from 120s+ to <100ms
    - User-perceived load time: Instant dashboard rendering

- **Exchange Sync Service Optimization**:
  - Reduced `page_size` from 200 to 50 for order history sync
  - Added 15-second startup delay to allow initial HTTP requests to complete
  - Optimized sync intervals to prevent resource contention

- **Frontend Loading Strategy**:
  - Changed from sequential to parallel API calls
  - All endpoints (top coins, portfolio, orders, config) load simultaneously
  - Signal hydration loads first batch immediately, continues in background

#### Bug Fixes

- **Telegram Alerts**: Fixed Telegram Notifier not sending alerts
  - Corrected `os.getenv()` to properly use default values when env vars are empty strings
  - Explicit None check instead of falsy check
  - Telegram now correctly sends buy signals and alerts

- **Telegram /watchlist Command**: Fixed command showing "No coins with Trade=YES"
  - Changed query to show only coins with `trade_enabled=True` (not all coins)
  - Added status indicators (✅ Trade, 🔔 Alert)
  - Fixed field name from `last_price` to `price`

- **SL/TP Values**: Fixed SL/TP showing "Calculating..." in frontend
  - Ensured `res_up`, `res_down`, `current_price`, `resistance_up`, `resistance_down` always have valid values
  - Added default calculated values if missing from database
  - Fallback to percentage-based calculation when resistance levels unavailable
  - Fixed `signal_writer.py` syntax errors
  - Forced `market-updater` to use PostgreSQL instead of SQLite

- **Volume Figures**: Fixed volume changing very fast in frontend
  - Changed from `random.uniform()` to deterministic hash-based calculation
  - Ensured `volume_ratio` is always calculated and included
  - Volume figures are now stable and deterministic

- **ALERT Button**: Fixed network error when pressing ALERT button
  - Corrected `get_db()` generator to re-raise exceptions instead of yielding None
  - Implemented comprehensive exception handling with rollback and proper cleanup
  - Simplified `simulate_alert` endpoint to avoid asyncio event loop conflicts
  - Forced PostgreSQL usage in backend service

- **ETH_USDT Trade Status**: Fixed `trade_enabled` disappearing on dashboard refresh
  - Improved logging in `update_dashboard_item()` to preserve existing values
  - Merge updates instead of overwriting existing values
  - Only update non-None values
  - Restored ETH_USDT to `trade_enabled=True`

- **Duplicate Watchlist Items**: Cleaned up duplicate ETH_USDT entries in database

- **Database Session Management**: Fixed `get_db()` generator error handling
  - Implemented comprehensive exception handling with rollback
  - Proper cleanup in finally block
  - Prevents silent failures

- **API Response Parsing**: Fixed "body stream already read" errors
  - Frontend reads response body exactly once (as text, then safe JSON.parse)
  - Backend always returns JSON, even on errors
  - Consistent error handling across all API calls

### Changed

#### Infrastructure

- **Docker Compose**: Refactored to use `local` and `aws` profiles
  - **Local Profile**:
    - Backend on port 8002, no gluetun dependency
    - Direct port access (backend:8002, frontend:3000)
    - Development-friendly configuration
  
  - **AWS Profile**:
    - Backend uses gluetun for outbound VPN traffic
    - Hardened PostgreSQL with explicit connection strings
    - Production-ready security and monitoring
  
  - Forced `DATABASE_URL` to ensure PostgreSQL usage

- **Database**: All services now explicitly use PostgreSQL (no SQLite fallback)
  - Removed SQLite fallback completely
  - Ensures all services use the same database
  - Prevents data synchronization problems

- **SSH Infrastructure Hardening**:
  - All deployment scripts must source `scripts/ssh_key.sh`
  - No raw `ssh`, `scp`, or `rsync` commands allowed in operational scripts
  - No `.pem` files, `ssh-agent`, or `ssh-add` usage
  - Validator script enforces these rules automatically

#### Performance Optimizations

- Exchange sync service now starts with 15s delay
- Reduced page size for order history sync
- Optimized dashboard queries with proper limits
- Improved background service scheduling
- Added composite database indexes for faster queries
- Implemented SQL aggregation for portfolio totals

#### Logging

- Enhanced logging throughout the application
  - Changed verbose warnings to debug level
  - Added performance timing logs (`[PERF]` prefix)
  - Improved error context and stack traces
  - Better debugging capabilities
  - Reduced log noise in production

#### API Configuration

- **Endpoint-Specific Timeouts**:
  - `/signals`: 15s (with circuit breaker)
  - `/market/top-coins-data`: 60s
  - `/orders/history`: 60s
  - `/dashboard/state`: 45s
  - Watchlist alerts: 15s
  - Custom coin add: 30s

- **Circuit Breaker Pattern** (for `/signals` endpoint):
  - Failure threshold: 3 failures
  - Auto-reset after 30 seconds
  - Timeouts don't count as failures
  - Deduplicated error logs to prevent noise

### API Endpoint Specifications

#### `GET /api/dashboard/state`
- **Purpose**: Unified dashboard state endpoint
- **Response Time**: <1 second (optimized)
- **Returns**: Portfolio, signals, open orders, bot status

#### `GET /api/trading/live-status`
- **Purpose**: Get current LIVE/DRY_RUN mode
- **Response Format**: `{ ok: true, success: true, live_trading_enabled, mode, message }`
- **Always returns JSON**

#### `POST /api/trading/live-toggle`
- **Purpose**: Toggle LIVE_TRADING mode
- **Request**: `{ "enabled": true }`
- **Response**: Always JSON (never HTML, even on errors)
- **Implementation**:
  - Persists setting in database (`TradingSettings` table with key `LIVE_TRADING`)
  - Updates environment variable for current process
  - Frontend reads response body once to prevent "body stream already read" errors

#### `GET /api/health`
- **Purpose**: Health check endpoint
- **Nginx Configuration**: Exact match proxy to `__ping`
- **Ensures health checks always reach backend**

### Database Schema

#### Key Tables

- **Watchlist**: Stores coin configurations and trading settings
  - Fields: `symbol`, `trade_enabled`, `sl_percentage`, `tp_percentage`, etc.

- **ExchangeBalance**: Stores current exchange balances
  - Fields: `asset`, `free`, `locked`, `total`

- **ExchangeOrder**: Stores all exchange orders (open and executed)
  - Fields: `exchange_order_id`, `symbol`, `side`, `status`, `price`, `quantity`, etc.

- **TradeSignal**: Stores trading signals with technical indicators
  - Fields: `symbol`, `rsi`, `ma50`, `ma200`, `ema10`, `atr`, `resistance_up/down`, etc.

- **TradingSettings**: Stores platform-wide settings
  - Key: `LIVE_TRADING` (value: "true" or "false")

### Security Considerations

#### API Authentication
- Current implementation: Header-based `x-api-key: demo-key`
- **Note**: Should be replaced with proper authentication in production

#### Nginx Security Headers
- `X-Frame-Options: SAMEORIGIN`
- `X-Content-Type-Options: nosniff`
- `X-XSS-Protection: 1; mode=block`

#### TLS Configuration
- Enforced TLS 1.2+
- Modern cipher suites only
- HSTS headers (recommended for production)

### Deployment & Operations

#### DRY_RUN Mode

All deployment scripts support `DRY_RUN=1` mode:
```bash
DRY_RUN=1 ./scripts/start-stack-and-health.sh
# Outputs all commands that would run, without executing
# Shows resolved SERVER, paths, and SSH commands
# Skips sleep/stabilization periods
```

**Benefits**:
- Zero-risk testing: Test deployments without touching production
- Predictable deployments: All commands are previewed before execution
- Early error detection: Catch configuration errors before deployment
- Audit trail: Complete log of what would be executed

#### Pre-Deployment Validation

The validation system prevents deployment errors before they occur:
1. **SSH System Validation**: Ensures all scripts use unified SSH helpers
2. **DRY_RUN Simulations**: Tests all deployment scripts without execution
3. **Explicit Confirmation**: Production deployments require user confirmation
4. **Post-Deployment Verification**: Provides commands to verify deployment success

### Technical Debt

- Identified inconsistency in open orders between `/api/orders/open` (queries SQLite + PostgreSQL) and `/api/dashboard/state` (queries only PostgreSQL)
  - **Impact**: Non-critical, but should be unified
  - **Recommendation**: Deprecate SQLite completely, use PostgreSQL exclusively

- Old order `OPEN0004` from Oct 26 still showing as ACTIVE in SQLite
  - **Recommendation**: Implement automated cleanup job for stale orders

### Testing & Validation

#### Pre-Deployment Checklist
- [x] Dashboard loads in <1 second
- [x] Telegram `/watchlist` command shows correct coins
- [x] ALERT button sends notifications
- [x] SL/TP values display correctly
- [x] Volume figures are stable
- [x] Open orders sync from exchange
- [x] LIVE/DRY_RUN toggle works correctly
- [x] SSH system validation passes
- [x] DRY_RUN simulations complete successfully

#### Performance Benchmarks

**Before Version 4.0:**
- Dashboard endpoint: 120+ seconds
- Database queries: 60+ seconds
- User-perceived load: 2+ minutes

**After Version 4.0:**
- Dashboard endpoint: <1 second
- Database queries: <100ms
- User-perceived load: Instant

### Migration Guide

#### From Version 1.0.0 to 4.0

**Local Development:**
```bash
cd /path/to/automated-trading-platform
docker compose --profile local down
docker compose --profile local pull
docker compose --profile local up -d db backend frontend
```

**AWS Production:**
```bash
cd /path/to/automated-trading-platform
docker compose --profile aws down
docker compose --profile aws pull
docker compose --profile aws up -d
```

**Database Migration:**
- No schema changes required
- Ensure `DATABASE_URL` points to PostgreSQL (SQLite no longer supported)

### Documentation

- Created comprehensive technical description (`docs/VERSION_4.0_TECHNICAL_DESCRIPTION.md`)
- Created performance investigation log (`perf_investigation_log.md`)
- Created fix summaries for each issue
- Added inline comments explaining optimizations
- Updated deployment guide with SSH validation and DRY_RUN flow
- Created internal knowledge base (`docs/project-overview.md`, `docs/decisions-log.md`)

### Conclusion

Version 4.0 represents a significant milestone in the platform's evolution, delivering:

- **99%+ performance improvement** in dashboard loading (2+ minutes → <1 second)
- **7 critical bug fixes** improving reliability and user experience
- **Complete infrastructure hardening** with unified SSH system and validation
- **Production-ready deployment** with DRY_RUN, pre-flight checks, and safety confirmations
- **Robust API communication** with consistent JSON responses and error handling
- **Comprehensive health monitoring** with systemd timers and Telegram alerts

The release establishes a solid foundation for future development while addressing immediate production concerns, user experience issues, and deployment safety. The hardened SSH infrastructure and validation system ensure that deployments are predictable, auditable, and safe.

## [1.0.0] - Previous Version

Initial stable release.

