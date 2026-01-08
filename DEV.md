# Local Development Guide

This guide explains how to set up and run the application locally for fast development with hot reload.

## Prerequisites

- Docker and Docker Compose installed
- Git
- (Optional) VS Code or your preferred IDE

## Quick Start

### 1. Setup Environment Variables

```bash
cd /Users/carloscruz/automated-trading-platform

# Copy the example env file for local development
cp .env.local.example .env.local

# Edit .env.local with your configuration (at minimum, review the settings)
# For local dev, defaults are usually fine - just make sure RUN_TELEGRAM=false
nano .env.local  # or use your preferred editor
```

**Important**: 
- Set `RUN_TELEGRAM=false` to prevent accidental Telegram alerts during development
- Set `LIVE_TRADING=false` to prevent accidental trades
- The default database password is `traderpass` (change if needed)
- Frontend port is configured via `FRONTEND_PORT` in `.env.local` (defaults to 3001)
  - The frontend dev script reads `FRONTEND_PORT` from your environment
  - If not set, it defaults to 3001
  - To override: `export FRONTEND_PORT=3001` before running `npm run dev`
- **Optional**: If you need additional secrets (e.g., API keys for testing), create `.env.secrets.local` manually. It's git-ignored and will be auto-loaded by docker-compose if present.

### 2. Start Services

```bash
cd /Users/carloscruz/automated-trading-platform

# Start all services (database, backend, frontend)
docker compose --profile local up -d

# Or start with logs visible (recommended first time)
docker compose --profile local up
```

**What happens:**
- PostgreSQL database starts on port 5432
- Backend API starts on port 8002 with **hot reload enabled** (`--reload` flag)
- Frontend starts on port 3001 with **hot reload enabled** (`npm run dev`)

### 3. Access the Application

- **Frontend**: http://localhost:3001
- **Backend API**: http://localhost:8002
- **API Docs**: http://localhost:8002/docs

### 4. Dev Proxy (API Routing)

The frontend uses Next.js rewrites to proxy API requests to the backend during development. This allows the frontend to use relative paths (e.g., `/health/system`, `/dashboard/state`) which are automatically routed to the backend API.

**Proxied paths:**
- `/health/:path*` → `${BACKEND_URL}/api/health/:path*`
- `/dashboard/:path*` → `${BACKEND_URL}/api/dashboard/:path*`
- `/market/:path*` → `${BACKEND_URL}/api/market/:path*`
- `/orders/:path*` → `${BACKEND_URL}/api/orders/:path*`
- `/signals/:path*` → `${BACKEND_URL}/api/signals/:path*`

**Configuration:**
- `BACKEND_URL` is set in `frontend/.env.local` (default: `http://localhost:8002`)
- The proxy only works in development mode (Next.js dev server)
- In production, API calls use absolute URLs configured via `NEXT_PUBLIC_API_URL`

**Example:**
```bash
# Frontend request: GET http://localhost:3001/health/system
# Proxied to: GET http://localhost:8002/api/health/system
```

### 5. Verify Services are Running

```bash
cd /Users/carloscruz/automated-trading-platform

# Check container status
docker compose --profile local ps

# Check logs
docker compose --profile local logs -f

# Check backend health
curl http://localhost:8002/api/health

# Check frontend
curl http://localhost:3001

# Or use the verification script
./scripts/dev-check.sh
```

## Development Workflow

### Hot Reload

Both frontend and backend support hot reload:

- **Frontend**: Edit files in `frontend/` directory → Changes appear automatically in browser
- **Backend**: Edit files in `backend/` directory → Server automatically restarts and reloads

**No need to rebuild Docker images or restart containers!**

### Making Changes

1. Edit code in your IDE
2. Save the file
3. Changes are automatically picked up:
   - Frontend: Browser refreshes automatically (Next.js Fast Refresh)
   - Backend: Server restarts automatically (uvicorn --reload)

### Viewing Logs

```bash
cd /Users/carloscruz/automated-trading-platform

# All services
docker compose --profile local logs -f

# Backend only
docker compose --profile local logs -f backend

# Frontend only
docker compose --profile local logs -f frontend

# Database only
docker compose --profile local logs -f db
```

### Stopping Services

```bash
cd /Users/carloscruz/automated-trading-platform

# Stop services (containers remain)
docker compose --profile local stop

# Stop and remove containers
docker compose --profile local down

# Stop and remove containers + volumes (⚠️ deletes database data)
docker compose --profile local down -v
```

### Restarting Services

```bash
cd /Users/carloscruz/automated-trading-platform

# Restart all services
docker compose --profile local restart

# Restart specific service
docker compose --profile local restart backend
docker compose --profile local restart frontend
```

## Database

### Accessing the Database

```bash
cd /Users/carloscruz/automated-trading-platform

# Connect to PostgreSQL via Docker
docker compose --profile local exec db psql -U trader -d atp

# Or use a GUI tool (DBeaver, pgAdmin, etc.)
# Connection details:
#   Host: localhost
#   Port: 5432
#   Database: atp
#   User: trader
#   Password: traderpass (or your .env.local value)
```

### Running Migrations

```bash
cd /Users/carloscruz/automated-trading-platform

# Execute migration script inside backend container
docker compose --profile local exec backend python scripts/your_migration.py
```

## Troubleshooting

### Services Won't Start

1. **Check if ports are already in use:**
   ```bash
   # Check if port 3001 is in use (frontend)
   lsof -i :3001
   
   # Check if port 8002 is in use (backend)
   lsof -i :8002
   
   # Check if port 5432 is in use (database)
   lsof -i :5432
   ```
   
   **Note:** The frontend runs on port **3001** (not 3000). This is configured in `.env.local` via `FRONTEND_PORT=3001`.

2. **Check Docker is running:**
   ```bash
   docker ps
   ```

3. **Check logs for errors:**
   ```bash
   docker compose --profile local logs
   ```

### Backend Not Reloading

- Ensure `--reload` flag is in docker-compose.yml (line 98)
- Check backend logs: `docker compose --profile local logs -f backend`
- Verify volume mount: `docker compose --profile local exec backend ls -la /app`

### Frontend Not Reloading

- Check frontend logs: `docker compose --profile local logs -f frontend`
- Verify volume mount: `docker compose --profile local exec frontend ls -la /app`
- Clear browser cache or do hard refresh (Cmd+Shift+R on Mac)
- **Port confusion:** Ensure you're accessing http://localhost:3001 (not 3000). The frontend port is configured via `FRONTEND_PORT` in `.env.local` (defaults to 3001).

### Database Connection Errors

1. **Check database is running:**
   ```bash
   docker compose --profile local ps db
   ```

2. **Check database logs:**
   ```bash
   docker compose --profile local logs db
   ```

3. **Verify DATABASE_URL in .env.local:**
   ```bash
   grep DATABASE_URL .env.local
   ```
   Should be: `DATABASE_URL=postgresql://trader:traderpass@db:5432/atp`

### Changes Not Appearing

1. **Verify volume mounts are working:**
   ```bash
   # Backend
   docker compose --profile local exec backend ls -la /app/app/main.py
   
   # Frontend
   docker compose --profile local exec frontend ls -la /app/src/app/page.tsx
   ```

2. **Check file permissions:**
   ```bash
   ls -la backend/app/main.py
   ls -la frontend/src/app/page.tsx
   ```

3. **Rebuild if necessary (rare):**
   ```bash
   docker compose --profile local build --no-cache backend
   docker compose --profile local up -d backend
   ```

### Connection Refused (ERR_CONNECTION_REFUSED)

If you see connection refused errors:

1. **Frontend not running:**
   ```bash
   # Check if frontend is running on port 3001
   lsof -i :3001
   
   # Start frontend
   cd frontend && npm run dev
   ```

2. **Backend not running:**
   ```bash
   # Check if backend is running on port 8002
   lsof -i :8002
   
   # Start backend
   docker compose --profile local up -d backend-dev
   ```

3. **Wrong port:** Ensure you're accessing http://localhost:3001 (not 3000). The frontend port is configured in `.env.local` via `FRONTEND_PORT=3001`.

### CORS Errors

If you see CORS errors in the browser console:

- The backend is configured to allow requests from `localhost:3000` and `localhost:3001` (plus `127.0.0.1` variants).
- Ensure `FRONTEND_URL` in `docker-compose.yml` matches your frontend port.
- If you changed the frontend port, update `.env.local` with `FRONTEND_PORT=<new_port>` and restart the backend.

### Quick Verification

Use the verification script to check everything at once:

```bash
./scripts/dev-check.sh
```

This checks:
- Ports 3001 and 8002 are listening
- Backend health endpoint responds
- Frontend responds
- Provides actionable error messages

### Docker Compose "env file not found" Errors

If you see errors like:
```
env file .../.env.secrets.local not found: stat ... no such file or directory
```

**Solution:** This file is optional and has been removed from the required `env_file` list in `docker-compose.yml`. The error should not occur anymore. If you need additional secrets for local testing:

1. Create `.env.secrets.local` manually in the repo root
2. Add your test secrets (never commit this file - it's git-ignored)
3. Docker Compose will automatically load it if present

**Note:** For normal local development, `.env` and `.env.local` are sufficient.

### Out of Memory Errors

If you get out of memory errors:

```bash
# Increase Docker memory limit in Docker Desktop settings
# Or reduce resource limits in docker-compose.yml
```

## Common Commands Reference

```bash
cd /Users/carloscruz/automated-trading-platform

# Start services
docker compose --profile local up -d

# View logs
docker compose --profile local logs -f

# Stop services
docker compose --profile local stop

# Restart services
docker compose --profile local restart

# Rebuild and restart (if needed)
docker compose --profile local build --no-cache
docker compose --profile local up -d

# Execute command in container
docker compose --profile local exec backend python --version
docker compose --profile local exec frontend npm --version

# Access shell in container
docker compose --profile local exec backend sh
docker compose --profile local exec frontend sh

# Clean up everything (⚠️ removes database data)
docker compose --profile local down -v
```

## Docker Build Contexts (Local vs AWS)

The backend uses **separate Dockerfiles** for local and AWS builds to avoid context mismatches:

| Environment | Build Context | Dockerfile | COPY Paths |
|------------|---------------|------------|------------|
| **Local** | `./backend` | `Dockerfile` | No `backend/` prefix (e.g., `COPY requirements.txt`) |
| **AWS** | `.` (repo root) | `Dockerfile.aws` | With `backend/` prefix (e.g., `COPY backend/requirements.txt`) |

**Why?** Docker COPY paths are relative to the build context. Local services use `context: ./backend`, so files are at the root. AWS uses `context: .`, so files are in `backend/` subdirectory.

**Validation:** Run the verification script to ensure both builds work:
```bash
./scripts/verify-docker-contexts.sh
```

This script:
- Validates docker-compose configuration
- Builds local images (backend-dev, market-updater)
- Builds AWS image (backend-aws)
- Fails fast with clear errors if any build breaks

**⚠️ Important:** When modifying Dockerfiles:
- **Never** add conditional COPY logic to support both contexts
- **Always** keep local and AWS Dockerfiles separate
- **Always** run `./scripts/verify-docker-contexts.sh` after changes

## Safety Notes

⚠️ **Important Safety Reminders:**

1. **Never enable Telegram in local dev**: Set `RUN_TELEGRAM=false` in `.env.local`
2. **Never enable live trading in local dev**: Set `LIVE_TRADING=false` in `.env.local`
3. **Local database is separate**: Changes in local DB don't affect staging/prod
4. **Don't commit .env.local**: It's in .gitignore for a reason

## Next Steps

Once local development is working:
- See [DEPLOY.md](./DEPLOY.md) for deploying to staging/production
- See [GIT_WORKFLOW.md](./GIT_WORKFLOW.md) for Git branching strategy


