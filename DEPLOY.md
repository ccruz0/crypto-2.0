# Deployment Guide

This guide explains how to deploy the application to AWS staging and production environments.

## Environments

- **Local**: Development on your machine (see [DEV.md](./DEV.md))
- **Staging**: AWS environment for validation (optional, can use same instance with different config)
- **Production**: AWS environment for live trading and alerts

## Prerequisites

- AWS EC2 instance access (SSH or AWS SSM Session Manager)
- Docker and Docker Compose installed on AWS instance
- Environment variables configured (`.env.aws` on AWS instance)
- AWS credentials configured (for GitHub Actions if using CI/CD)

## Current AWS Setup

- **Instance**: EC2 (i-08726dc37133b2454, ap-southeast-1)
- **Domain**: dashboard.hilovivo.com
- **Nginx**: Reverse proxy (systemd service, not in Docker)
- **Docker Compose**: Services run with `--profile aws`

## Deployment Workflow

### Option 1: Manual Deployment (SSH)

```bash
# 1. SSH into AWS instance
ssh ubuntu@YOUR_AWS_IP
# Or use AWS SSM Session Manager
aws ssm start-session --target i-08726dc37133b2454

# 2. Navigate to project directory
cd ~/automated-trading-platform
# or
cd /home/ubuntu/automated-trading-platform

# 3. Pull latest code
git pull origin main

# 4. (Optional) Update frontend submodule if using separate repo
# git submodule update --init --recursive

# 5. Rebuild and restart services
docker compose --profile aws down
docker compose --profile aws build --no-cache
docker compose --profile aws up -d

# 6. Wait for services to be healthy
sleep 30

# 7. Check service status
docker compose --profile aws ps

# 8. Verify backend health
curl http://localhost:8002/ping_fast

# 9. Restart nginx to reconnect to services
sudo systemctl restart nginx
```

### Option 2: GitHub Actions (Automated)

Deployment is automated via GitHub Actions when you push to `main` branch.

**Workflow file**: `.github/workflows/deploy_session_manager.yml`

**What it does:**
1. Checks out code
2. Fetches/clones frontend repo
3. Connects to AWS via SSM Session Manager
4. Pulls latest code on AWS
5. Rebuilds Docker images
6. Restarts services
7. Verifies deployment

**To trigger:**
```bash
git push origin main
```

**To view deployment logs:**
- Go to GitHub repository → Actions tab
- Click on the latest workflow run

### Option 3: Deployment Script (SSM)

Use deployment scripts like `deploy_lifecycle_events_fix.sh`:

```bash
# Run deployment script from local machine
./deploy_lifecycle_events_fix.sh

# Or use AWS SSM directly
aws ssm send-command \
  --instance-ids i-08726dc37133b2454 \
  --region ap-southeast-1 \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/automated-trading-platform",
    "git pull origin main",
    "docker compose --profile aws build --no-cache",
    "docker compose --profile aws up -d"
  ]'
```

## Environment Configuration

### Production Environment Variables

On AWS instance, create/update `.env.aws`:

```bash
# SSH into AWS instance
ssh ubuntu@YOUR_AWS_IP

# Edit environment file
cd ~/automated-trading-platform
nano .env.aws

# Or copy from example (⚠️ fill in real values!)
cp .env.prod.example .env.aws
nano .env.aws
```

**Critical variables to verify:**
- `LIVE_TRADING=true` (production only!)
- `RUN_TELEGRAM=true` (production only!)
- `TELEGRAM_CHAT_ID` (correct production channel)
- `POSTGRES_PASSWORD` (strong password)
- `SECRET_KEY` (strong secret key)
- `EXCHANGE_CUSTOM_API_KEY` and `EXCHANGE_CUSTOM_API_SECRET` (production credentials)

### Staging Environment (Optional)

If you want a separate staging environment:

1. **Option A**: Use separate AWS instance
   - Create new EC2 instance
   - Use `.env.staging.example` as template
   - Deploy with `--profile aws` (or create staging profile)

2. **Option B**: Use same instance, different database
   - Use different `POSTGRES_DB` in `.env.staging`
   - Use different `TELEGRAM_CHAT_ID` for staging alerts
   - Deploy to staging with different compose file or profile

## Deployment Checklist

### Before Deployment

- [ ] Code reviewed and tested locally
- [ ] All tests passing (if applicable)
- [ ] Environment variables verified
- [ ] Database migrations reviewed (if any)
- [ ] Backup production database (if deploying to prod)
- [ ] Verify `LIVE_TRADING` setting is correct for target environment
- [ ] Verify `TELEGRAM_CHAT_ID` is correct for target environment

### During Deployment

- [ ] Pull latest code
- [ ] Rebuild Docker images
- [ ] Stop old containers
- [ ] Start new containers
- [ ] Wait for health checks
- [ ] Verify services are running
- [ ] Restart nginx (if needed)
- [ ] Test API endpoints
- [ ] Test frontend

### After Deployment

- [ ] Verify backend health: `curl http://localhost:8002/ping_fast`
- [ ] Check frontend: Visit https://dashboard.hilovivo.com
- [ ] Check logs: `docker compose --profile aws logs -f`
- [ ] Monitor for errors (first 5-10 minutes)
- [ ] Verify Telegram alerts work (if production)
- [ ] Rollback plan ready (if issues)

## Rollback Procedure

If deployment causes issues:

```bash
# SSH into AWS instance
ssh ubuntu@YOUR_AWS_IP
cd ~/automated-trading-platform

# Option 1: Revert to previous git commit
git log --oneline  # Find previous commit
git reset --hard PREVIOUS_COMMIT_HASH
docker compose --profile aws build --no-cache
docker compose --profile aws up -d

# Option 2: Stop services (if critical issue)
docker compose --profile aws down

# Option 3: Restart services (if minor issue)
docker compose --profile aws restart
```

## Monitoring

### View Logs

```bash
# SSH into AWS instance
ssh ubuntu@YOUR_AWS_IP

# All services
cd ~/automated-trading-platform
docker compose --profile aws logs -f

# Backend only
docker compose --profile aws logs -f backend-aws

# Frontend only
docker compose --profile aws logs -f frontend-aws

# Last 100 lines
docker compose --profile aws logs --tail=100
```

### Check Service Status

```bash
# Container status
docker compose --profile aws ps

# Resource usage
docker stats

# Backend health
curl http://localhost:8002/ping_fast

# Frontend health
curl http://localhost:3000
```

### Nginx Status

```bash
# Check nginx status
sudo systemctl status nginx

# View nginx logs
sudo tail -f /var/log/nginx/error.log
sudo tail -f /var/log/nginx/access.log

# Test nginx configuration
sudo nginx -t

# Restart nginx
sudo systemctl restart nginx
```

## Troubleshooting

### Services Won't Start

1. **Check logs:**
   ```bash
   docker compose --profile aws logs
   ```

2. **Check disk space:**
   ```bash
   df -h
   docker system df
   ```

3. **Check Docker:**
   ```bash
   docker ps
   docker images
   ```

4. **Clean up if needed:**
   ```bash
   docker system prune -a
   docker volume prune
   ```

### Backend Health Check Failing

1. **Check backend logs:**
   ```bash
   docker compose --profile aws logs backend-aws
   ```

2. **Check database connection:**
   ```bash
   docker compose --profile aws exec backend-aws python -c "from app.database import engine; engine.connect()"
   ```

3. **Increase health check timeout** (if startup is slow):
   - Edit `docker-compose.yml` → `backend-aws` → `healthcheck` → `start_period`

### Nginx 502 Errors

1. **Check if services are running:**
   ```bash
   docker compose --profile aws ps
   ```

2. **Check nginx error log:**
   ```bash
   sudo tail -f /var/log/nginx/error.log
   ```

3. **Restart nginx:**
   ```bash
   sudo systemctl restart nginx
   ```

4. **Verify service ports:**
   ```bash
   netstat -tlnp | grep :8002
   netstat -tlnp | grep :3000
   ```

### Database Issues

1. **Check database logs:**
   ```bash
   docker compose --profile aws logs db
   ```

2. **Check database connection:**
   ```bash
   docker compose --profile aws exec db psql -U trader -d atp -c "SELECT 1;"
   ```

3. **Backup database:**
   ```bash
   docker compose --profile aws exec db pg_dump -U trader atp > backup.sql
   ```

## Safety Notes

⚠️ **Critical Safety Reminders:**

1. **Production Deployment:**
   - Always test in staging/local first
   - Verify `LIVE_TRADING=true` is intentional
   - Verify `TELEGRAM_CHAT_ID` is correct production channel
   - Backup database before major changes
   - Deploy during low-traffic periods if possible

2. **Never:**
   - Use `--reload` flag in production (causes 502 errors)
   - Enable volume mounts in production (security risk)
   - Commit `.env.aws` or `.env.prod` to git
   - Deploy untested code to production
   - Skip health checks

3. **Staging:**
   - Use test/sandbox API credentials if available
   - Use separate Telegram channel for staging alerts
   - Use separate database for staging

## Next Steps

- See [DEV.md](./DEV.md) for local development setup
- See [GIT_WORKFLOW.md](./GIT_WORKFLOW.md) for Git branching strategy
- Review [DEPLOYMENT_POLICY.md](./DEPLOYMENT_POLICY.md) for detailed deployment policies


