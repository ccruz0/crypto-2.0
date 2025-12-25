# Automated Trading Platform

A full-stack automated trading platform built with FastAPI (backend) and Next.js (frontend).

[![Dashboard Data Integrity](https://github.com/ccruz0/crypto-2.0/actions/workflows/dashboard-data-integrity.yml/badge.svg)](https://github.com/ccruz0/crypto-2.0/actions/workflows/dashboard-data-integrity.yml)

## 🚨 Deployment Policy

**⚠️ IMPORTANT: All production operations are executed via SSH on the EC2 instance. Production services run as Docker Compose containers using the AWS profile.**

For complete deployment guidelines, see: **[DEPLOYMENT_POLICY.md](DEPLOYMENT_POLICY.md)** and **[docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md)**

**Key Points:**
- ✅ All production operations via SSH on AWS EC2 instance
- ✅ Production services run as Docker Compose containers using `--profile aws`
- ✅ The supported commands are `docker compose --profile aws ...`
- ❌ Uvicorn `--reload` is forbidden in production (causes restarts and 502s)

## Runtime Architecture

**⚠️ IMPORTANT: AWS is the ONLY live production runtime (trading + alerts).**

- **AWS Backend** (Docker Compose): The only place where SignalMonitorService, scheduler, and Telegram bot run for production trading and alerts. Services run in Docker Compose containers using the `--profile aws` profile. Operations are executed via SSH on the EC2 instance.
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

**Deployment**: All production operations are done via SSH on AWS EC2. Services run using Docker Compose with `--profile aws`. See [DEPLOYMENT_POLICY.md](DEPLOYMENT_POLICY.md) and [docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md) for complete deployment guidelines.

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

- **Database**: PostgreSQL (Docker Compose)
- **Backend**: FastAPI with Gunicorn/Uvicorn (Docker Compose with `--profile aws` in production)
- **Frontend**: Next.js with TypeScript (Docker Compose with `--profile aws` in production)

**Note**: Production services run in Docker Compose containers using `--profile aws`, managed via SSH on AWS EC2. Local development uses `--profile local`. See [DEPLOYMENT_POLICY.md](DEPLOYMENT_POLICY.md) and [docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md) for details.

## Getting Started

### Production (AWS Only)

**The production runtime is on AWS. All operations are executed via SSH on the EC2 instance.**

**Basic Operations (execute via SSH on EC2):**
```bash
# Connect to AWS EC2
ssh ubuntu@<AWS_EC2_IP>

# Navigate to project directory
cd /home/ubuntu/automated-trading-platform

# Check service status
docker compose --profile aws ps

# View logs
docker compose --profile aws logs -n 200 backend-aws
docker compose --profile aws logs -n 200 frontend-aws

# Restart services
docker compose --profile aws restart backend-aws

# Pull latest images and deploy
docker compose --profile aws pull
docker compose --profile aws up -d --remove-orphans
```

**📌 AWS → Crypto.com Connection:**
For production AWS deployment, see [`docs/AWS_CRYPTO_COM_CONNECTION.md`](docs/AWS_CRYPTO_COM_CONNECTION.md) for the standard connection configuration.

**For detailed deployment procedures, see:**
- [DEPLOYMENT_POLICY.md](DEPLOYMENT_POLICY.md) - Deployment policy and workflow
- [docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md) - Single source of truth for AWS deployment commands

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

## Pre-commit Checks

This repository uses [pre-commit](https://pre-commit.com) to automatically run code quality checks before each commit. The hooks will:

- **Python**: Format with `black` and lint with `ruff` on all Python files
- **Frontend**: Format with `prettier` and lint with `eslint --fix` on staged TypeScript/JavaScript files
- **Tests**: Run backend tests (`pytest -q`) and frontend lint (`npm run lint`)

### Installation

1. Install pre-commit:
   ```bash
   pip install pre-commit
   ```

2. Enable the hooks:
   ```bash
   pre-commit install
   ```

### Usage

- Hooks run automatically on `git commit`
- To run manually on all files:
  ```bash
  pre-commit run --all-files
  ```
- To run on staged files only:
  ```bash
  pre-commit run
  ```

If any hook fails, the commit will be blocked. Fix the issues and try committing again.

## Troubleshooting

### Dashboard Not Loading (502 / Blank UI)

If the dashboard at https://dashboard.hilovivo.com is not loading:

1. **Quick diagnostic**: Run the automated diagnostic script:
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   bash scripts/debug_dashboard_remote.sh
   ```

   This comprehensive script automatically checks:
   - ✅ All container statuses and health (backend, frontend, db, gluetun, market-updater)
   - ✅ Backend API connectivity (host network and Docker network)
   - ✅ Database connectivity from backend
   - ✅ External endpoint tests (domain → nginx → services)
   - ✅ Recent error logs from all services
   - ✅ Nginx status and error logs
   - ✅ Provides color-coded output with clear status indicators

2. **Detailed troubleshooting**: See [Dashboard Health Check Runbook](docs/runbooks/dashboard_healthcheck.md) for:
   - Complete architecture diagrams
   - Request flow explanations
   - Step-by-step diagnostic workflows
   - Decision trees for common failure modes
   - Common fixes and solutions

3. **System overview**: See [Dashboard Diagnostic System](docs/monitoring/DASHBOARD_DIAGNOSTIC_SYSTEM.md) for:
   - Complete system architecture
   - Diagnostic script features
   - Common failure modes and solutions
   - Integration with runbook

## Environment Variables

See `.env.example` for all available environment variables and their descriptions.

