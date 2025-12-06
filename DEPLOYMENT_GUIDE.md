# Deployment Guide - Frontend Updates

## Problem
The frontend uses a production Docker build without mounted volumes. This means:
- Every code change requires a full Docker image rebuild
- Changes don't appear until the image is rebuilt and container restarted
- Browser cache can also prevent seeing updates

## Solutions

### Option 1: Quick Update Script (Recommended for Development)
Use the `deploy_frontend_update.sh` script:

```bash
./deploy_frontend_update.sh
```

This script:
1. Copies updated frontend files to AWS
2. Rebuilds the frontend Docker image
3. Restarts the frontend container
4. Waits for health check

### Option 2: Development Mode with Hot Reload
For faster iteration during development, temporarily modify `docker-compose.yml`:

```yaml
frontend-aws:
  # ... existing config ...
  volumes:
    - ./frontend:/app
    - /app/node_modules
    - /app/.next
  command: npm run dev
  # Remove read_only: true temporarily
```

**⚠️ WARNING**: Only use this for development. Revert to production build before deploying to production.

### Option 3: Full Production Deploy
For production deployments, use the full sync script:

```bash
./sync_to_aws.sh
```

## Preventing Future Issues

### 1. Always Rebuild After Code Changes
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker compose -f docker-compose.yml build frontend-aws && docker compose -f docker-compose.yml up -d frontend-aws'
```

### 2. Clear Browser Cache
After deploying, users should:
- Hard refresh: `Ctrl+Shift+R` (Windows/Linux) or `Cmd+Shift+R` (Mac)
- Or clear browser cache completely

### 3. Verify Deployment
Check that the code is in the container:
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'docker compose -f docker-compose.yml exec frontend-aws grep -n "Minimum Price Change" /app/src/app/page.tsx'
```

### 4. Check Build Logs
Verify the build completed successfully:
```bash
ssh -i ~/.ssh/id_rsa ubuntu@175.41.189.249 'cd ~/automated-trading-platform && docker compose -f docker-compose.yml build frontend-aws 2>&1 | tail -20'
```

## Best Practices
## SSH Validation & DRY_RUN Deployment Flow

This project enforces a strict SSH validation and dry-run process before any production deploy.

### What the validator checks
- Operational scope only:
  - `scripts/*.sh`, `deploy_*.sh`, `backend/*.sh`
- Ignores noise:
  - `node_modules`, `docs`, `tests`, `examples`, `tmp`, `.github`, `.vscode`, `assets`, `static`, `public`, `scripts/archive`, `scripts/experimental`
  - Markdown/JS/TS files
  - Echo/comments/heredocs in `.sh` files
- Flags only real executable commands starting with: `ssh`, `scp`, `rsync`, `ssh-agent`, `ssh-add`
- `.pem` and key-agent usage are flagged only if in executable code (not comments/strings).

### Operational scripts
- `scripts/ssh_key.sh` (helper; defines `ssh_cmd`, `scp_cmd`, `rsync_cmd`)
- `scripts/start-aws-stack.sh`, `scripts/start-stack-and-health.sh`
- `scripts/pre_deploy_check.sh`, `scripts/simulate_deploy.sh`, `scripts/deploy_production.sh`
- Other deployment helpers under `scripts/` and `backend/*.sh`, `deploy_*.sh`

### How to run DRY_RUN checks
1) Pre-deployment validation:
```bash
DRY_RUN=1 ./scripts/pre_deploy_check.sh
```
Expected output (no violations):
- Validator PASS summary with:
  - Scripts checked: X
  - Operational scripts skipped: Y
  - Violations found: 0
- DRY_RUN of `start-stack-and-health.sh` prints the exact remote sequence without executing it
- DRY_RUN of `start-aws-stack.sh` prints pull/up/ps/health-check commands and skips sleeps

2) End-to-end simulation:
```bash
DRY_RUN=1 ./scripts/simulate_deploy.sh
```
Expected:
- Runs the validator, DRY_RUN of both start scripts, and prints a final:
  - `[SUCCESS] Deployment simulation completed. Real deployment safe.`

### Production rule
- Do not deploy to AWS unless both DRY_RUN checks pass with zero violations.

### Real deployment command
```bash
SERVER=175.41.189.249 ./scripts/deploy_production.sh
```
This re-runs the pre-deployment checks, asks for explicit confirmation, and then starts the stack and health monitors on the remote host.
## Quick Start (AWS stack + health monitors)

Start full stack and install monitors in one command:

```bash
SERVER=175.41.189.249 ./scripts/start-stack-and-health.sh
```

Verify from local:

```bash
curl -k https://dashboard.hilovivo.com/api/health
curl -k https://dashboard.hilovivo.com/api/trading/live-status
curl -k -X POST https://dashboard.hilovivo.com/api/trading/live-toggle \
  -H "Content-Type: application/json" \
  -d '{"enabled": true}'
```

1. **Always rebuild after code changes** - The production build doesn't use volumes
2. **Test locally first** - Use `docker compose --profile local up frontend` for testing
3. **Use the update script** - `deploy_frontend_update.sh` automates the process
4. **Clear browser cache** - Users need to hard refresh after updates
5. **Monitor logs** - Check frontend logs after deployment: `docker compose logs frontend-aws`

## Troubleshooting

### Changes not appearing?
1. Verify code is on server: `grep "your change" ~/automated-trading-platform/frontend/src/app/page.tsx`
2. Rebuild image: `docker compose build frontend-aws`
3. Restart container: `docker compose up -d frontend-aws`
4. Clear browser cache: Hard refresh (`Ctrl+Shift+R`)
5. Check build logs for errors: `docker compose build frontend-aws 2>&1 | grep error`

### Build failing?
1. Check for syntax errors locally first
2. Verify all dependencies are in `package.json`
3. Check Node.js version compatibility
4. Review build logs for specific error messages

