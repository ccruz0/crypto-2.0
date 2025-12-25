# AWS Deployment Contract

**Single source of truth for AWS production deployment operations.**

This document defines the canonical commands and procedures for operating the production environment on AWS EC2.

---

## Environment

- **EC2 Instance Path**: `/home/ubuntu/automated-trading-platform`
- **SSH Prefix Convention**: All commands are executed via SSH on the EC2 instance
- **Docker Compose Profile**: `--profile aws`

---

## Standard Operations

### Connect to AWS EC2

```bash
ssh ubuntu@<AWS_EC2_IP>
# Or use your configured SSH alias/keys
```

### Navigate to Project Directory

```bash
cd /home/ubuntu/automated-trading-platform
```

---

## Command Reference

### Service Status

```bash
# Check all services status
docker compose --profile aws ps
```

### View Logs

```bash
# Backend logs (last 200 lines)
docker compose --profile aws logs -n 200 backend-aws

# Frontend logs (last 200 lines)
docker compose --profile aws logs -n 200 frontend-aws

# Follow logs in real-time
docker compose --profile aws logs -f backend-aws
docker compose --profile aws logs -f frontend-aws

# All services logs
docker compose --profile aws logs -n 200
```

### Restart Services

```bash
# Restart specific service
docker compose --profile aws restart backend-aws
docker compose --profile aws restart frontend-aws

# Restart all services
docker compose --profile aws restart
```

### Deploy Updates

```bash
# Pull latest images
docker compose --profile aws pull

# Deploy/update services
docker compose --profile aws up -d --remove-orphans
```

### Stop Services

```bash
# Stop specific service
docker compose --profile aws stop backend-aws

# Stop all services
docker compose --profile aws down
```

---

## Never Do

**Hard rules for production:**

1. ❌ **Never use `uvicorn --reload`** in production
   - Backend uses Gunicorn (NOT uvicorn with --reload)
   - Using `--reload` causes service restarts and 502 errors
   - See `docker-compose.yml` backend-aws service command

2. ❌ **Never mix systemd and Docker Compose** for the same service
   - Pick one management method and stick with it

3. ❌ **Never use profiles other than `aws`** for production deployments on AWS EC2

4. ❌ **Never run production services outside of Docker Compose** when using the AWS profile

---

## Services

Production services defined in `docker-compose.yml` with `--profile aws`:

- **backend-aws**: FastAPI backend (Gunicorn + Uvicorn workers)
- **frontend-aws**: Next.js frontend
- **db**: PostgreSQL database
- **market-updater-aws**: Market data updater service

---

## Health Checks

```bash
# Backend health check
curl http://localhost:8002/api/health

# Frontend health check
curl http://localhost:3000/
```

---

## Related Documentation

- [DEPLOYMENT_POLICY.md](../../DEPLOYMENT_POLICY.md) - Deployment policy and workflow
- [README.md](../../README.md) - Project overview and getting started

---

**Last Updated**: 2025-01-XX
**Status**: Active and Enforced

