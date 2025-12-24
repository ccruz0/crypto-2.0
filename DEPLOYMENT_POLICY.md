# Deployment Policy

## ⚠️ Official Deployment Policy

**Effective immediately, all production deployments MUST follow this policy.**

---

## Core Principles

### 1. Direct SSH Deployment Only

**All deployments MUST be performed directly via SSH on the AWS EC2 instance.**

- ✅ **Allowed**: Direct SSH connections to AWS EC2 instance
- ✅ **Allowed**: SSH-based deployment scripts that execute commands directly on the server
- ✅ **Allowed**: Direct file synchronization via `rsync` or `scp` over SSH
- ❌ **Prohibited**: Docker-based deployments
- ❌ **Prohibited**: Docker Compose workflows
- ❌ **Prohibited**: Container-based deployment methods

### 2. Docker is Disabled

**Docker is CLOSED and will NOT be used for deployments.**

- ❌ Docker containers are NOT to be used for production deployments
- ❌ `docker compose` commands are NOT to be used for deployment
- ❌ Docker images are NOT to be built or transferred as part of deployment
- ❌ Container-based service management is NOT permitted

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
   cd ~/automated-trading-platform
   ```

3. **Pull Latest Code** (if using Git)
   ```bash
   git pull origin main
   ```

4. **Deploy Services Directly**

   **Backend Deployment:**
   ```bash
   cd ~/automated-trading-platform/backend
   
   # Set up virtual environment
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   
   # Stop existing service
   pkill -f "uvicorn app.main:app" || true
   
   # Start service directly (no Docker)
   nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &
   ```

   **Frontend Deployment:**
   ```bash
   cd ~/automated-trading-platform/frontend
   
   # Install dependencies
   npm install
   
   # Build
   npm run build
   
   # Start service directly (no Docker)
   npm start
   ```

5. **Verify Deployment**
   ```bash
   # Check if services are running
   ps aux | grep uvicorn
   ps aux | grep node
   
   # Check service health
   curl http://localhost:8000/api/health
   ```

---

## Deployment Scripts

### Available SSH-Based Deployment Scripts

The following scripts are approved for use as they deploy directly via SSH without Docker:

- `backend/deploy_backend_aws.sh` - Backend deployment via SSH
- `deploy_backend_full.sh` - Full backend deployment via SSH
- `deploy_frontend_update.sh` - Frontend deployment via SSH
- Any script that uses `ssh`, `rsync`, or `scp` to deploy directly

### Prohibited Deployment Methods

The following are **NOT** to be used:

- `sync_to_aws.sh` (uses Docker)
- `.github/workflows/deploy.yml` (if it uses Docker)
- Any script containing `docker compose` commands
- Any script that builds or transfers Docker images

---

## Database Migrations

Database migrations must also be performed directly via SSH:

```bash
# Connect via SSH
ssh ubuntu@<AWS_EC2_IP>
cd ~/automated-trading-platform

# Run migrations directly (no Docker exec)
cd backend
source venv/bin/activate
python scripts/apply_migration_previous_price.py
```

---

## Service Management

### Starting Services

Services must be started directly on the host system:

```bash
# Backend
cd ~/automated-trading-platform/backend
source venv/bin/activate
nohup python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > backend.log 2>&1 &

# Frontend
cd ~/automated-trading-platform/frontend
nohup npm start > frontend.log 2>&1 &
```

### Stopping Services

```bash
# Backend
pkill -f "uvicorn app.main:app"

# Frontend
pkill -f "node.*frontend"
```

### Checking Service Status

```bash
# Check processes
ps aux | grep uvicorn
ps aux | grep node

# Check logs
tail -f ~/automated-trading-platform/backend/backend.log
tail -f ~/automated-trading-platform/frontend/frontend.log
```

---

## Environment Configuration

Environment variables must be configured directly on the server:

```bash
# Create/edit .env file directly on server
cd ~/automated-trading-platform/backend
nano .env

# Or use a deployment script that sets environment variables via SSH
```

---

## Verification Checklist

Before considering a deployment complete:

- [ ] Code deployed via SSH (not Docker)
- [ ] Services started directly on host (no containers)
- [ ] Environment variables configured on server
- [ ] Database migrations applied (if needed)
- [ ] Services verified running (`ps aux | grep`)
- [ ] Health checks passing (`curl http://localhost:8000/api/health`)
- [ ] Logs checked for errors

---

## Important Notes

1. **No Docker Dependency**: All deployment processes must work without Docker being installed or running.

2. **Direct Process Management**: Services run as direct processes on the EC2 instance, not in containers.

3. **SSH-Based Tools Only**: Only use SSH, rsync, scp, and direct command execution. No container orchestration tools.

4. **Logs Location**: Service logs are written directly to files on the filesystem (e.g., `backend.log`, `frontend.log`), not to Docker logs.

---

## Migration from Docker

If you have existing Docker-based deployments, they must be migrated to direct SSH deployments:

1. Stop all Docker containers
2. Deploy services directly on the host
3. Update all deployment scripts to use SSH instead of Docker
4. Remove Docker-based deployment workflows

---

## Questions or Clarifications

If you have questions about this policy or need clarification on deployment procedures, refer to:

- SSH-based deployment scripts in the repository
- AWS EC2 instance documentation
- Direct service management guides

---

**Last Updated**: $(date)

**Policy Status**: Active and Enforced

