# Automated Trading Platform

A full-stack automated trading platform built with FastAPI (backend) and Next.js (frontend).

## Runtime Architecture

**⚠️ IMPORTANT: AWS is the ONLY live production runtime (trading + alerts).**

- **AWS Backend Container**: The only place where SignalMonitorService, scheduler, and Telegram bot run for production trading and alerts.
- **Local Mac**: Used ONLY for:
  - Development (edit code, run tests)
  - Git operations
  - SSH-based diagnostics and helper scripts that connect to AWS
  - **NOT** a second live trading/alerts environment

**Do NOT run a local backend with SignalMonitorService or scheduler in parallel with AWS, as this would:**
- Create duplicate alerts
- Cause Telegram bot conflicts (409 errors)
- Create duplicate orders
- Cause data inconsistencies

For production, use AWS only. Local docker-compose is for development/testing only.

## Project Structure

```
automated-trading-platform/
├── backend/
│   └── app/
│       ├── api/          # API routes
│       ├── core/         # Core configuration
│       ├── models/       # Database models
│       ├── schemas/      # Pydantic schemas
│       ├── services/     # Business logic
│       ├── utils/        # Utility functions
│       ├── deps/         # Dependencies
│       └── tests/        # Test files
├── frontend/             # Next.js application
├── docker-compose.yml    # Docker services
└── .env.example         # Environment variables template
```

## Services

- **Database**: PostgreSQL
- **Backend**: FastAPI with Uvicorn
- **Frontend**: Next.js with TypeScript
- **Containerization**: Docker & Docker Compose

## Getting Started

### Production (AWS Only)

**The production runtime is on AWS. To check health:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/check_runtime_health_aws.sh
```

**To view logs:**
```bash
cd /Users/carloscruz/automated-trading-platform
bash scripts/aws_backend_logs.sh --tail 200
```

### Local Development (Dev Only - NOT Production)

**⚠️ WARNING: Local setup is for development only. Do NOT use for production trading.**

1. Copy the environment variables:
   ```bash
   cp .env.example .env
   ```

2. Update the `.env` file with your actual values.

3. Start the services (local dev only):
   ```bash
   docker-compose --profile local up -d
   ```

4. Access the applications:
   - Frontend: http://localhost:3000
   - Backend API: http://localhost:8002
   - API Documentation: http://localhost:8002/docs

**Note:** Local backend will start SignalMonitorService and scheduler, but this should ONLY be used for development/testing, never in parallel with AWS production.

## Development

**⚠️ NOTE: These commands are for LOCAL DEVELOPMENT ONLY. They will start SignalMonitorService and scheduler locally, which should NOT be run in parallel with AWS production.**

### Backend Development (Local Dev Only)
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

**Warning:** This starts a local backend with SignalMonitorService, scheduler, and Telegram bot. Only use this for development/testing. Do NOT run in parallel with AWS production.

### Frontend Development
```bash
cd frontend
npm install
npm run dev
```

## Troubleshooting

### Dashboard Not Loading (502 / Blank UI)

If the dashboard at https://dashboard.hilovivo.com is not loading:

1. **Quick diagnostic**: Run the automated diagnostic script:
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/debug_dashboard_remote.sh
   ```

2. **Detailed troubleshooting**: See [Dashboard Health Check Runbook](docs/runbooks/dashboard_healthcheck.md) for step-by-step diagnostics and common fixes.

The diagnostic script checks:
- Container status and health
- Backend API connectivity
- Market-updater health
- Recent logs from backend and market-updater
- Nginx error logs

## Environment Variables

See `.env.example` for all available environment variables and their descriptions.

