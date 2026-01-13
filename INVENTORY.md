# Deployment & Runtime Setup Inventory

## Current Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         LOCAL MAC                                │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Frontend    │  │   Backend    │  │  PostgreSQL  │         │
│  │  Next.js     │  │   FastAPI    │  │   Docker     │         │
│  │  Port 3000   │  │  Port 8002   │  │  Port 5432   │         │
│  │              │  │              │  │              │         │
│  │ Dockerfile.dev│ │  Dockerfile  │  │  Dockerfile  │         │
│  │ npm run dev  │  │  uvicorn     │  │  (hardened)  │         │
│  │              │  │  (NO reload) │  │              │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         │                  │                  │                 │
│         └──────────────────┴──────────────────┘                 │
│                    docker-compose --profile local               │
│                    ⚠️ Volume mounts enabled                     │
│                    ⚠️ BUT backend missing --reload flag         │
└─────────────────────────────────────────────────────────────────┘

                              │
                              │ git push / SSH deploy
                              ▼

┌─────────────────────────────────────────────────────────────────┐
│                        AWS EC2 INSTANCE                          │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │  NGINX (System Service)                                  │  │
│  │  Port 443 (HTTPS) → Port 80 (HTTP redirect)             │  │
│  │  dashboard.hilovivo.com                                  │  │
│  │  ├─ / → frontend-aws:3000                                │  │
│  │  └─ /api → backend-aws:8002                              │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │  Frontend    │  │   Backend    │  │  PostgreSQL  │         │
│  │  Next.js     │  │   FastAPI    │  │   Docker     │         │
│  │  Port 3000   │  │  Port 8002   │  │  Port 5432   │         │
│  │              │  │              │  │              │         │
│  │  Dockerfile  │  │  Dockerfile  │  │  Dockerfile  │         │
│  │  Production  │  │  Gunicorn    │  │  (hardened)  │         │
│  │  Build       │  │  (NO reload) │  │              │         │
│  │              │  │  ⚠️ NO volumes│ │              │         │
│  └──────────────┘  └──────────────┘  └──────────────┘         │
│         │                  │                  │                 │
│         └──────────────────┴──────────────────┘                 │
│                    docker compose --profile aws                 │
│                    ✅ Production build (no volumes)             │
│                    ✅ Gunicorn (not uvicorn --reload)           │
└─────────────────────────────────────────────────────────────────┘
```

## Key Files Inventory

### Docker Configuration

#### `docker-compose.yml`
- **Location**: Root directory
- **Profiles**: `local`, `aws`
- **Services**:
  - `db`: PostgreSQL (both profiles)
  - `backend`: FastAPI (local profile, port 8002)
    - **Command**: `uvicorn` with 3 workers (NO --reload)
    - **Volume mount**: `./backend:/app` ✅
    - **Issue**: Missing `--reload` flag for hot reload
  - `backend-aws`: FastAPI (aws profile, port 8002)
    - **Command**: `gunicorn` (production, NO reload) ✅
    - **Volume mount**: Commented out (production) ✅
  - `frontend`: Next.js (local profile, port 3000)
    - **Dockerfile**: `Dockerfile.dev` ✅
    - **Command**: `npm run dev` ✅ (hot reload enabled)
    - **Volume mount**: `./frontend:/app`, `/app/node_modules` ✅
  - `frontend-aws`: Next.js (aws profile, port 3000)
    - **Dockerfile**: `Dockerfile` (production build) ✅
    - **Command**: `node server.js` (production) ✅
    - **Volume mount**: Commented out (production) ✅
  - `market-updater`: Background service (local profile)
  - `market-updater-aws`: Background service (aws profile)

#### Dockerfiles

**Backend** (`backend/Dockerfile`):
- Multi-stage build (builder + runner)
- Python 3.11 (aiohttp compatibility)
- Non-root user: `appuser`
- Entrypoint: `entrypoint.sh`
- CMD: `uvicorn app.main:app --host 0.0.0.0 --port 8002`
- Build fingerprint support (GIT_SHA, BUILD_TIME)

**Frontend Production** (`frontend/Dockerfile`):
- Multi-stage build (deps + builder + runner)
- Node 22 Alpine
- Production build with standalone output
- Non-root user: `app`
- CMD: `node server.js`

**Frontend Dev** (`frontend/Dockerfile.dev`):
- Single stage (Node 22 Alpine)
- Installs dependencies
- CMD: `npm run dev` ✅ (hot reload enabled)

**PostgreSQL** (`docker/postgres/Dockerfile`):
- Hardened PostgreSQL with scram-sha-256 auth
- Security: no-new-privileges, cap_drop=ALL

### Environment Files

**Current Setup**:
- `.env`: Common variables (shared)
- `.env.local`: Local-specific variables
- `.env.aws`: AWS-specific variables
- **Missing**: Example/template files for new developers

**Key Variables** (from docker-compose.yml):
- Database: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`
- Environment: `ENVIRONMENT`, `APP_ENV`, `RUNTIME_ORIGIN`
- API URLs: `API_BASE_URL`, `FRONTEND_URL`, `NEXT_PUBLIC_API_URL`
- Telegram: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- Trading: `LIVE_TRADING`, `USE_CRYPTO_PROXY`, `CRYPTO_PROXY_URL`
- Backend: `UVICORN_WORKERS`, `DISABLE_AUTH`, `ENABLE_CORS`

### Reverse Proxy

**Nginx** (`nginx/dashboard.conf`):
- **Location**: `/etc/nginx/sites-available/` on AWS
- **Domain**: `dashboard.hilovivo.com`
- **SSL**: Let's Encrypt certificates
- **Routes**:
  - `/` → `http://localhost:3000` (frontend)
  - `/api` → `http://localhost:8002/api` (backend)
  - `/api/monitoring/` → Rate limited (5 req/s)
  - `/api/health` → Backend health check
- **Rate Limiting**: 10 req/s for API, 5 req/s for monitoring
- **NOT in docker-compose**: Runs as systemd service on AWS

### Deployment Scripts

**AWS Deployment**:
- `.github/workflows/deploy_session_manager.yml`: GitHub Actions CI/CD
  - Triggers on push to `main`
  - Uses AWS SSM (Session Manager)
  - Commands: `git pull`, `docker compose --profile aws build`, `docker compose --profile aws up -d`
- `deploy_lifecycle_events_fix.sh`: Example deployment script
  - Uses AWS SSM
  - Instance ID: `i-08726dc37133b2454`
  - Region: `ap-southeast-1`
- Multiple `deploy_*.sh` scripts: Various deployment scripts

**Local Development**:
- `scripts/check-and-start-services.sh`: **DISABLED** (shows error message)
- Current workflow: Edit code → Build Docker images → Deploy to AWS → Test (SLOW)

### AWS Runtime

**Services on AWS**:
- **Docker Compose**: Runs with `--profile aws`
- **Nginx**: Systemd service (not in Docker)
- **Crypto Proxy**: Optional systemd service (`crypto-proxy.service`)
- **Instance**: EC2 (i-08726dc37133b2454, ap-southeast-1)
- **Domain**: dashboard.hilovivo.com

**Startup**:
- Manual: `ssh` → `cd ~/automated-trading-platform` → `docker compose --profile aws up -d`
- GitHub Actions: Automatic on push to `main`
- No systemd service for docker-compose (manual/CI-driven)

### Backend Startup

**Local Profile** (docker-compose.yml line 98):
```bash
python -m uvicorn app.main:app --host 0.0.0.0 --port 8002 --workers 3 ...
```
- ❌ **Missing `--reload` flag** (needed for hot reload)

**AWS Profile** (docker-compose.yml line 189):
```bash
python -m gunicorn app.main:app -w 1 -k uvicorn.workers.UvicornWorker ...
```
- ✅ Correct (Gunicorn, no reload)

### Frontend Startup

**Local Profile** (docker-compose.yml line 308):
```bash
npm run dev
```
- ✅ Correct (Next.js dev server with hot reload)

**AWS Profile**:
- Uses `node server.js` from production build
- ✅ Correct (production mode)

## Current Workflow Issues

1. **Local Development**:
   - ✅ Volume mounts exist
   - ✅ Frontend hot reload works
   - ❌ Backend missing `--reload` flag (requires container restart for code changes)
   - ❌ No clear documentation for local dev setup

2. **AWS Deployment**:
   - ✅ Production build (no volumes)
   - ✅ Gunicorn (not uvicorn --reload)
   - ✅ Separate staging/prod distinction unclear
   - ✅ Deployment scripts exist but workflow is manual

3. **Missing**:
   - ❌ `.env` template files for new developers
   - ❌ Clear local dev setup instructions
   - ❌ Staging environment (only local + AWS/prod)
   - ❌ Git branching strategy documentation

## Recommendations

1. **Add `--reload` to backend command in local profile** (docker-compose.yml line 98)
2. **Create `.env.*.example` template files**
3. **Create `DEV.md` with local development instructions**
4. **Create `DEPLOY.md` with staging/prod deployment instructions**
5. **Add Git branching strategy documentation**
6. **Consider adding staging environment** (separate docker-compose profile or separate AWS instance)



