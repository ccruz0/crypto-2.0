# Local Development Setup - Hot Reload Backend

## Overview

A dedicated `backend-dev` service has been added for fast hot-reload local development. This service:
- ✅ Mounts only source code (preserves installed packages)
- ✅ Uses uvicorn with `--reload` for automatic code reloading
- ✅ Uses only local environment files (`.env` + `.env.local`, NOT `.env.aws`)
- ✅ Safe defaults: trading disabled, telegram disabled, proxy disabled
- ✅ Fast healthchecks and no unnecessary delays
- ✅ Keeps AWS deployment completely unchanged

## Files Changed

1. **`docker-compose.yml`**
   - Added `backend-dev` service (local profile only)
   - Kept existing `backend` service unchanged (for backward compatibility)
   - AWS `backend-aws` service unchanged

2. **`backend/Makefile`**
   - Added dev commands: `dev-up`, `dev-logs`, `dev-restart`, `dev-down`

3. **`verify_local_dev.sh`** (new)
   - Verification script to test the setup

4. **`LOCAL_DEV_SETUP.md`** (this file)
   - Documentation

## Environment Configuration

### Environment Files

`backend-dev` uses **only local environment files**:
- `.env` - Base configuration
- `.env.local` - Local overrides
- **NOT `.env.aws`** - Avoids AWS config conflicts in local dev

### Default Environment Variables

The `backend-dev` service sets safe defaults for local development:

```yaml
ENVIRONMENT=local
APP_ENV=local
RUNTIME_ORIGIN=LOCAL
TRADING_ENABLED=false      # Trading disabled by default
LIVE_TRADING=false         # Live trading disabled
RUN_TELEGRAM=false         # Telegram disabled
USE_CRYPTO_PROXY=false     # Proxy disabled by default
FRONTEND_URL=http://localhost:3000  # Frontend on port 3000
DISABLE_AUTH=true          # Auth disabled for local dev
ENABLE_CORS=1              # CORS enabled
PYTHONUNBUFFERED=1         # Unbuffered Python output
```

### Overriding Defaults

To override defaults, add them to `.env.local`:

```bash
# Example: Enable crypto proxy for local dev
USE_CRYPTO_PROXY=true
CRYPTO_PROXY_URL=http://host.docker.internal:9000
CRYPTO_PROXY_TOKEN=your-token

# Example: Enable trading (use with caution!)
TRADING_ENABLED=true
LIVE_TRADING=true
```

## Enable Live Portfolio

To see real portfolio data in the Portfolio tab, you can use one of these methods:

### Method 1: Crypto.com API Credentials (Primary)

Configure Crypto.com Exchange API credentials for live data.

### Required Environment Variables

The exact environment variable names used by the Crypto.com client in this repo are:

```bash
# Create .env.secrets.local in repo root (NEVER commit this file!)
# This file is automatically loaded by backend-dev service
EXCHANGE_CUSTOM_API_KEY=your_api_key_here
EXCHANGE_CUSTOM_API_SECRET=your_api_secret_here
```

**Note:** The credential resolver also supports these alternative names (first match wins):
- `CRYPTO_COM_API_KEY` + `CRYPTO_COM_API_SECRET`
- `CRYPTOCOM_API_KEY` + `CRYPTOCOM_API_SECRET`

But `missing_env` will always return canonical names: `EXCHANGE_CUSTOM_API_KEY`, `EXCHANGE_CUSTOM_API_SECRET`

### Setup Steps

1. **Create API Key in Crypto.com Exchange:**
   - Log in to Crypto.com Exchange
   - Go to API Key settings
   - Create a new API key with **Read** permission enabled
   - Copy the API key and secret

2. **Whitelist Your IP:**
   - In the API key settings, add your server's IP address to the allowlist
   - For local dev, this is your machine's public IP (not localhost)
   - You can check your IP: `curl https://api.ipify.org`

3. **Create `.env.secrets.local` in repo root:**
   ```bash
   # In ~/automated-trading-platform/.env.secrets.local
   EXCHANGE_CUSTOM_API_KEY=your_actual_api_key
   EXCHANGE_CUSTOM_API_SECRET=your_actual_api_secret
   ```
   
   **Important:**
   - File is automatically loaded by `backend-dev` service (local profile only)
   - File is gitignored (never committed)
   - These are Crypto.com **Exchange** API keys (not the mobile app)
   - Required permissions: **Read** (at minimum)

4. **Restart Backend:**
   ```bash
   cd backend && make dev-restart
   ```

### Error Codes

- **40101**: Authentication failure
  - Check: API key/secret are correct
  - Check: API key has **Read** permission
  - Check: API key is not disabled/suspended

- **40103**: IP not whitelisted
  - Add your server's IP address to the API key allowlist in Crypto.com Exchange settings
  - Your current outbound IP may differ from expected

### Quick Test Commands

```bash
# Test portfolio snapshot endpoint
curl -sS http://localhost:8002/api/portfolio/snapshot | python3 -m json.tool

# Run evidence collection
cd frontend && npm run qa:portfolio-watchlist
```

### Verifying Credentials (without exposing them)

```bash
# Check if credentials are loaded (shows preview, not full values)
docker compose --profile local logs backend-dev | grep "CRYPTO_AUTH_DIAG"

# Or enable diagnostic logging temporarily:
# Add to .env.local: CRYPTO_AUTH_DIAG=true
# Then check logs for credential preview
```

### Expected Behavior

- **With valid credentials:** Portfolio shows real balances, positions, and totals
- **Without credentials:** Portfolio shows clear error message listing missing env vars
- **With invalid credentials:** Portfolio shows specific error (40101 or 40103) with instructions

### Method 2: Fallback Sources (When Crypto.com Auth Fails)

If Crypto.com blocks local auth (40101/40103), the Portfolio tab will automatically use fallback sources in local mode:

#### A) Derived from Trades (Automatic)

If you have executed orders in the database, holdings are automatically computed:
- BUY orders add to holdings
- SELL orders subtract from holdings
- Source: `derived_trades`
- Prices: CoinGecko → Yahoo Finance → stablecoin (1.0) → 0

#### B) Local JSON File (Manual)

Create `backend/app/data/local_portfolio.json`:

```json
{
  "BTC": 0.0123,
  "ETH": 0.5,
  "USDT": 1200
}
```

- Source: `local_file`
- Prices: Same fallback chain as above
- File is gitignored (not committed)

**Note:** Fallback only works when:
- `ENVIRONMENT=local` or `RUNTIME_ORIGIN=LOCAL`
- Crypto.com auth fails (40101/40103)
- At least one fallback source has data

The Portfolio tab will show a badge indicating the source: "Crypto.com", "Derived from Trades", or "Local File".

## Daily Commands

### Using Makefile (Recommended)

```bash
# Start db + backend-dev
cd backend && make dev-up

# Watch logs
cd backend && make dev-logs

# Restart backend-dev
cd backend && make dev-restart

# Stop backend-dev (keeps db running)
cd backend && make dev-down
```

### Using Docker Compose Directly

```bash
# Start
cd ~/automated-trading-platform
docker compose --profile local up -d --build db backend-dev

# Logs
cd ~/automated-trading-platform
docker compose --profile local logs -f backend-dev

# Restart
cd ~/automated-trading-platform
docker compose --profile local restart backend-dev

# Stop
cd ~/automated-trading-platform
docker compose --profile local stop backend-dev
```

## Verification

### Run Verification Script

```bash
./verify_local_dev.sh
```

This script will:
1. Check Docker daemon is running
2. Start db + backend-dev services
3. Wait for API to be ready (max 60s)
4. Test `/api/health` endpoint
5. Show service status

### Manual Test

```bash
curl -sS http://localhost:8002/api/health
```

Expected response:
```json
{"status":"ok","path":"/api/health"}
```

## Hot Reload Test

1. Edit a Python file in `backend/app/` (e.g., `backend/app/main.py`)
2. Watch the logs: `cd backend && make dev-logs`
3. You should see: `WARNING:  WatchFiles detected changes in 'app/main.py'. Reloading...`
4. The server automatically reloads within 1-2 seconds

## How It Works

1. **Dependencies**: Installed once in the Docker image (fast, stable)
2. **Source Code**: Mounted as volumes for hot-reload
   - `./backend/app:/app/app` - Python application code
   - `./backend/scripts:/app/scripts` - Scripts directory
3. **Uvicorn Reload**: Watches mounted directories for changes
4. **No Package Overwrite**: Only code is mounted, not site-packages
5. **Fast Startup**: No sleep delays, fast healthchecks (10s interval, 10s start_period)

## AWS Deployment

✅ **Completely unchanged** - `backend-aws` service uses:
- Gunicorn (not uvicorn)
- No volumes (production image)
- AWS profile only
- Uses `.env.aws` for configuration

Verify AWS is unchanged:
```bash
docker compose --profile aws config --services | grep backend
# Should show: backend-aws
```

## Services Overview

- **`backend-dev`**: Local development with hot-reload (local profile only)
  - Uses `.env` + `.env.local` only
  - Safe defaults (trading disabled, etc.)
  - Fast healthchecks
  - No delays
  
- **`backend`**: Original local service (unchanged, for backward compatibility)
  
- **`backend-aws`**: AWS production service (unchanged, AWS profile only)
  - Uses `.env.aws` for configuration
  - Production settings

## Troubleshooting

### Port 8002 already in use
```bash
# Stop existing backend service
docker compose --profile local stop backend

# Then start backend-dev
cd backend && make dev-up
```

### Changes not reloading
1. Check logs: `cd backend && make dev-logs`
2. Verify volumes are mounted: `docker inspect automated-trading-platform-backend-dev | grep -A 10 Mounts`
3. Ensure you're editing files in `backend/app/` directory

### API not responding
1. Check container is running: `docker ps | grep backend-dev`
2. Check logs: `cd backend && make dev-logs`
3. Check health: `curl http://localhost:8002/api/health`
4. Run verification script: `./verify_local_dev.sh`

### AWS config accidentally loaded
If you see AWS-related behavior in local dev:
1. Check `.env.local` doesn't have AWS vars
2. Verify `backend-dev` in docker-compose.yml doesn't include `.env.aws` in `env_file`
3. Restart: `cd backend && make dev-restart`
