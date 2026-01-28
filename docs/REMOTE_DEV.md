# Remote Development Guide

## Overview

This project now follows an **AWS-first development workflow**. All runtime services (backend, frontend, database) run exclusively on AWS. Local development is restricted to code editing, committing, and pushing. Local Docker usage is **completely disabled**.

## Key Principles

1. **Local development NEVER runs Docker containers**
2. **Local development NEVER sends Telegram messages**
3. **All runtime, testing, and deployment happens on AWS**
4. **AWS is the single source of truth for Telegram alerts**

---

## Local Development Workflow

### Prerequisites

- Git installed
- Code editor (VS Code, Cursor, etc.)
- SSH access to AWS configured (`hilovivo-aws`)

### Workflow Steps

1. **Edit Code Locally**
   ```bash
   cd /Users/carloscruz/automated-trading-platform
   # Edit files using your preferred editor
   ```

2. **Commit Changes**
   ```bash
   git add .
   git commit -m "Your commit message"
   ```

3. **Push to Repository**
   ```bash
   git push origin develop  # or main for production
   ```

4. **Never run Docker locally**
   - Scripts are disabled and will error if attempted
   - All Docker commands must be executed via SSH on AWS

---

## Remote (AWS) Workflow

### Initial Setup on AWS

1. **SSH to AWS**
   ```bash
   ssh hilovivo-aws
   ```

2. **Navigate to Project Directory**
   ```bash
   cd /home/ubuntu/automated-trading-platform
   ```

3. **Pull Latest Changes**
   ```bash
   git fetch origin
   git checkout develop  # or main for production
   git pull origin develop
   ```

4. **Rebuild Services**
   ```bash
   docker compose --profile aws down
   docker compose --profile aws up -d --build
   ```

5. **Verify Services are Running**
   ```bash
   docker compose --profile aws ps
   ```

6. **Check Logs**
   ```bash
   # Backend logs
   docker compose --profile aws logs -f backend-aws
   
   # Frontend logs
   docker compose --profile aws logs -f frontend-aws
   
   # All services
   docker compose --profile aws logs -f
   ```

### Daily Development Cycle

**From Local Machine:**

1. Edit code locally
2. Commit and push changes
3. Sync to AWS:
   ```bash
   ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'git pull origin develop && docker compose --profile aws up -d --build'"
   ```

**Or SSH into AWS and execute commands:**

```bash
ssh hilovivo-aws
cd /home/ubuntu/automated-trading-platform
git pull origin develop
docker compose --profile aws down
docker compose --profile aws up -d --build
```

---

## Production Workflow

### Deploying to Production

1. **Merge to Main Branch**
   ```bash
   git checkout main
   git merge develop
   git push origin main
   ```

2. **Deploy on AWS**
   ```bash
   ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'git fetch origin && git checkout main && git pull origin main && docker compose --profile aws down && docker compose --profile aws up -d --build'"
   ```

3. **Verify Deployment**
   ```bash
   ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws ps && curl -s http://localhost:8002/api/health'"
   ```

---

## Telegram Configuration

### Critical Rule

**Local development is FORBIDDEN from sending Telegram messages. AWS is the single source of truth for Telegram alerts.**

### How It Works

The system automatically determines whether Telegram should be enabled based on:

1. **Environment Variables:**
   - `ENVIRONMENT=aws` (AWS) or `ENVIRONMENT=local` (Local)
   - `APP_ENV=aws` (AWS) or `APP_ENV=local` (Local)
   - `RUN_TELEGRAM=true` (Enable) or `RUN_TELEGRAM=false` (Disable)

2. **Logic:**
   - Telegram is **ONLY** enabled if:
     - Environment is AWS (`ENVIRONMENT=aws` or `APP_ENV=aws`)
     - AND `RUN_TELEGRAM=true`
   - Local development **ALWAYS** disables Telegram, even if `RUN_TELEGRAM=true`

3. **Configuration:**
   - **AWS:** `.env.aws` should contain:
     ```bash
     ENVIRONMENT=aws
     APP_ENV=aws
     RUN_TELEGRAM=true
     TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
     TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
     ```
   
   - **Local:** `.env.local` should contain:
     ```bash
     ENVIRONMENT=local
     APP_ENV=local
     RUN_TELEGRAM=false
     # Telegram credentials are optional (will be ignored)
     ```

### Testing Locally

- Code compiles and runs without errors
- All Telegram calls return `False` silently
- Logs show: "Telegram disabled: Not on AWS or RUN_TELEGRAM not set to 'true'"
- No messages are sent to Telegram

---

## Canonical Commands

All commands must be prefixed with appropriate `cd` and executed via `sh -c "..."`.

### Start/Restart Dev Stack on AWS

```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws down && docker compose --profile aws up -d --build'"
```

### Check Service Status

```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws ps'"
```

### View Logs

```bash
# All services
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws logs --tail=100 -f'"

# Backend only
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws logs --tail=100 -f backend-aws'"

# Frontend only
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws logs --tail=100 -f frontend-aws'"

# Market updater
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws logs --tail=100 -f market-updater'"
```

### Sync Local Changes to AWS

```bash
# Option 1: Push to git, then pull on AWS
git push origin develop
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'git pull origin develop && docker compose --profile aws up -d --build'"

# Option 2: Direct sync (if using rsync/scp - not recommended, use git instead)
# Use git workflow instead for better version control
```

### Run Database Migrations

```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec backend-aws python -c \"from app.database import engine; from app.models import Base; Base.metadata.create_all(engine)\"'"
```

### Health Checks

```bash
# Backend health
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'curl -s http://localhost:8002/api/health'"

# Frontend health (if accessible)
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'curl -s http://localhost:3000/' | head -20"

# Database health
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec db pg_isready -U trader'"
```

### Diagnostic Commands

```bash
# Check running containers
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker ps'"

# Check Docker Compose configuration
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws config'"

# Check environment variables
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec backend-aws env | grep -E \"ENVIRONMENT|APP_ENV|RUN_TELEGRAM\"'"

# Check Telegram configuration
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec backend-aws env | grep -E \"TELEGRAM\"'"
```

### Deploy Production

```bash
# 1. Merge to main locally
git checkout main
git merge develop
git push origin main

# 2. Deploy on AWS
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'git fetch origin && git checkout main && git pull origin main && docker compose --profile aws down && docker compose --profile aws up -d --build'"

# 3. Verify
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws ps && curl -s http://localhost:8002/api/health'"
```

---

## Environment Configuration

### AWS Environment Variables (.env.aws)

```bash
ENVIRONMENT=aws
APP_ENV=aws
RUN_TELEGRAM=true
TELEGRAM_BOT_TOKEN=<REDACTED_TELEGRAM_TOKEN>
TELEGRAM_CHAT_ID=<REDACTED_TELEGRAM_CHAT_ID>
POSTGRES_PASSWORD=your_secure_password
LIVE_TRADING=true
# ... other AWS-specific variables
```

### Local Environment Variables (.env.local)

```bash
ENVIRONMENT=local
APP_ENV=local
RUN_TELEGRAM=false
# Telegram credentials are optional (ignored in local)
# ... other local-specific variables (if any)
```

---

## Troubleshooting

### Local Docker Scripts Try to Start

**Symptom:** Error when trying to run `start_local.sh` or `check-and-start-services.sh`

**Solution:** This is expected. These scripts are disabled. Use AWS workflow instead.

### Telegram Messages Not Sending from AWS

**Check 1: Environment Variables**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec backend-aws env | grep -E \"ENVIRONMENT|APP_ENV|RUN_TELEGRAM\"'"
```

Should show:
- `ENVIRONMENT=aws`
- `APP_ENV=aws`
- `RUN_TELEGRAM=true`

**Check 2: Backend Logs**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws logs backend-aws | grep -i telegram'"
```

Look for:
- `Telegram Notifier initialized` (good)
- `Telegram disabled: ...` (bad - check env vars)

### Services Not Starting on AWS

**Check Docker Compose Status:**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws ps'"
```

**Check Logs for Errors:**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws logs --tail=200'"
```

**Rebuild from Scratch:**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws down -v && docker compose --profile aws up -d --build'"
```

### Database Connection Issues

**Check Database is Running:**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec db pg_isready -U trader'"
```

**Check Database Connection from Backend:**
```bash
ssh hilovivo-aws "cd /home/ubuntu/automated-trading-platform && sh -c 'docker compose --profile aws exec backend-aws python -c \"from app.database import SessionLocal; db = SessionLocal(); db.execute(\"SELECT 1\"); print(\"DB OK\")\"'"
```

---

## Branch Strategy

- **`develop`**: Development branch (for AWS dev environment)
- **`main`**: Production branch (for AWS production environment)

### Workflow

1. Make changes locally
2. Commit to `develop`
3. Push `develop` → AWS pulls and tests
4. When ready, merge `develop` → `main`
5. Deploy `main` to AWS production

---

## Version Management

Current version: **0.45**

Version history is tracked in `frontend/src/app/page.tsx` in the `VERSION_HISTORY` constant. See the "Version History" tab in the dashboard for full changelog.

---

## Additional Resources

- **Docker Compose Profiles:**
  - `local`: Disabled (local Docker usage forbidden)
  - `aws`: Active (all runtime on AWS)

- **Service Ports:**
  - Backend: `8002`
  - Frontend: `3000`
  - Database: `5432`

- **SSH Connection:**
  - Host: `hilovivo-aws` (configured in `~/.ssh/config`)
  - Project Path: `/home/ubuntu/automated-trading-platform`

---

## Important Notes

1. **NEVER run Docker locally** - All scripts are disabled
2. **NEVER send Telegram from local** - Code compiles but calls are neutralized
3. **ALWAYS use AWS for testing** - Pull, rebuild, test on AWS
4. **ALWAYS use git workflow** - Push local changes, pull on AWS
5. **AWS is production-ready** - All Telegram alerts come from AWS only

---

**Last Updated:** 2025-11-23 (Version 0.45)

