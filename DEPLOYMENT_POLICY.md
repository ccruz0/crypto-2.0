# Deployment Policy

## ⚠️ Official Deployment Policy

**Effective immediately, all production deployments MUST follow this policy.**

---

## Core Principles

### 1. SSH-Based Operations

**All production operations MUST be performed directly via SSH on the AWS EC2 instance.**

- ✅ **Allowed**: Direct SSH connections to AWS EC2 instance
- ✅ **Allowed**: SSH-based deployment scripts that execute commands directly on the server
- ✅ **Allowed**: Direct file synchronization via `rsync` or `scp` over SSH

### 2. Docker Compose for Production Services

**Production services run as Docker Compose containers using the AWS profile.**

- ✅ Production services run using `docker compose --profile aws` commands
- ✅ All Docker Compose operations are executed via SSH on the EC2 instance
- ✅ Supported commands: `docker compose --profile aws ps`, `logs`, `restart`, `pull`, `up -d`
- ❌ **Forbidden**: Uvicorn `--reload` flag in production (causes restarts and 502s)
- ❌ **Forbidden**: Mixing systemd and Docker for the same service

---

## Required Deployment Process

### Standard Deployment Workflow

1. **Connect via SSH**
   ```bash
   ssh ubuntu@<AWS_EC2_IP>
   # Or use your configured SSH alias/keys
   ```

2. **Navigate to Project Directory**
   ```bash
   cd /home/ubuntu/automated-trading-platform
   ```

3. **Pull Latest Code** (if using Git)
   ```bash
   git pull origin main
   ```

4. **Deploy Services Using Docker Compose**

   **Pull Latest Images and Deploy:**
   ```bash
   cd /home/ubuntu/automated-trading-platform
   
   # Pull latest images
   docker compose --profile aws pull
   
   # Deploy/update services
   docker compose --profile aws up -d --remove-orphans
   ```

   **Note**: Services are defined in `docker-compose.yml` with the `aws` profile:
   - `backend-aws`: FastAPI backend (uses Gunicorn, NOT uvicorn with --reload)
   - `frontend-aws`: Next.js frontend
   - `db`: PostgreSQL database
   - `market-updater-aws`: Market data updater service

5. **Verify Deployment**
   ```bash
   # Check service status
   docker compose --profile aws ps
   
   # View logs
   docker compose --profile aws logs -n 200 backend-aws
   docker compose --profile aws logs -n 200 frontend-aws
   
   # Check service health
   curl http://localhost:8002/api/health
   ```

For detailed command reference, see [docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md).

---

## Deployment Scripts

### Approved Deployment Methods

The following are approved for production deployment:

- Scripts that use `docker compose --profile aws` commands via SSH
- SSH-based scripts that execute Docker Compose commands on the EC2 instance
- Scripts that use `ssh`, `rsync`, or `scp` to sync files and execute Docker Compose commands

### Prohibited Practices

The following are **NOT** permitted:

- ❌ Using `uvicorn --reload` in production (causes restarts and 502 errors)
- ❌ Mixing systemd services and Docker Compose for the same service
- ❌ Running production services outside of Docker Compose with `--profile aws`
- ❌ Using Docker Compose profiles other than `aws` for production

---

## Database Migrations

Database migrations can be run via Docker Compose:

```bash
# Connect via SSH
ssh ubuntu@<AWS_EC2_IP>
cd /home/ubuntu/automated-trading-platform

# Run migrations via Docker Compose
docker compose --profile aws exec backend-aws python scripts/apply_migration_previous_price.py
```

Alternatively, if you need to run migrations outside of Docker:

```bash
cd /home/ubuntu/automated-trading-platform/backend
source venv/bin/activate  # If virtualenv exists
python scripts/apply_migration_previous_price.py
```

---

## Service Management

### Starting Services

Services are managed via Docker Compose:

```bash
cd /home/ubuntu/automated-trading-platform

# Start all services
docker compose --profile aws up -d

# Start specific service
docker compose --profile aws up -d backend-aws
```

### Stopping Services

```bash
cd /home/ubuntu/automated-trading-platform

# Stop specific service
docker compose --profile aws stop backend-aws

# Stop all services
docker compose --profile aws down
```

### Checking Service Status

```bash
cd /home/ubuntu/automated-trading-platform

# Check service status
docker compose --profile aws ps

# View logs (last 200 lines)
docker compose --profile aws logs -n 200 backend-aws
docker compose --profile aws logs -n 200 frontend-aws

# Follow logs in real-time
docker compose --profile aws logs -f backend-aws
```

---

## Environment Configuration

Environment variables are configured via `.env.aws` file on the server:

```bash
# Edit environment file
cd /home/ubuntu/automated-trading-platform
nano .env.aws

# After editing, restart services to apply changes
docker compose --profile aws restart backend-aws
```

Environment variables are loaded via the `env_file` directive in `docker-compose.yml` for the `aws` profile services.

---

## Verification Checklist

Before considering a deployment complete:

- [ ] Code deployed via SSH
- [ ] Latest images pulled: `docker compose --profile aws pull`
- [ ] Services started/updated: `docker compose --profile aws up -d --remove-orphans`
- [ ] Services verified running: `docker compose --profile aws ps`
- [ ] Environment variables configured in `.env.aws`
- [ ] Database migrations applied (if needed)
- [ ] Health checks passing: `curl http://localhost:8002/api/health`
- [ ] Logs checked for errors: `docker compose --profile aws logs -n 200 backend-aws`
- [ ] Verified no `--reload` flag in production (backend uses Gunicorn)

---

## Important Notes

1. **SSH-Based Operations**: All deployment operations are executed via SSH on the EC2 instance.

2. **Docker Compose for Services**: Production services run as Docker Compose containers using the `--profile aws` profile.

3. **No Reload in Production**: Backend service uses Gunicorn (NOT uvicorn with `--reload`). The `--reload` flag causes restarts and 502 errors in production and is forbidden.

4. **Logs Access**: Service logs are accessed via `docker compose --profile aws logs` commands.

5. **Single Source of Truth**: For exact command reference, see [docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md).

---

## Never Do

**Hard rules for production:**

1. ❌ **Never use `uvicorn --reload`** in production. The backend-aws service uses Gunicorn which does not support reload. Using `--reload` causes service restarts and 502 errors.

2. ❌ **Never mix systemd and Docker Compose** for the same service. Pick one management method and stick with it.

3. ❌ **Never use profiles other than `aws`** for production deployments on AWS EC2.

4. ❌ **Never run production services outside of Docker Compose** when using the AWS profile.

---

## Questions or Clarifications

If you have questions about this policy or need clarification on deployment procedures, refer to:

- [docs/contracts/deployment_aws.md](docs/contracts/deployment_aws.md) - Single source of truth for AWS deployment commands
- SSH-based deployment scripts in the repository
- AWS EC2 instance documentation

---

**Last Updated**: $(date)

**Policy Status**: Active and Enforced

