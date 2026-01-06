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
- Frontend starts on port 3000 with **hot reload enabled** (`npm run dev`)

### 3. Access the Application

- **Frontend**: http://localhost:3000
- **Backend API**: http://localhost:8002
- **API Docs**: http://localhost:8002/docs

### 4. Verify Services are Running

```bash
cd /Users/carloscruz/automated-trading-platform

# Check container status
docker compose --profile local ps

# Check logs
docker compose --profile local logs -f

# Check backend health
curl http://localhost:8002/ping_fast

# Check frontend
curl http://localhost:3000
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
   # Check if port 3000 is in use
   lsof -i :3000
   
   # Check if port 8002 is in use
   lsof -i :8002
   
   # Check if port 5432 is in use
   lsof -i :5432
   ```

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


