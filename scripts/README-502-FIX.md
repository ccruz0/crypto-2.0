# 502 Bad Gateway Fix Script

## Overview

The `fix-502-aws.sh` script provides comprehensive diagnostics and automatic fixes for 502 Bad Gateway errors on the AWS server.

## Usage

```bash
# Use default server (47.130.143.159)
./scripts/fix-502-aws.sh

# Specify custom server IP
./scripts/fix-502-aws.sh 54.254.150.31

# Specify custom project directory
REMOTE_PROJECT_DIR=/path/to/project ./scripts/fix-502-aws.sh
```

## What It Does

The script performs the following checks and fixes:

### 1. Docker Services Check
- Verifies Docker is running
- Checks if `backend-aws` container is running
- Checks if `frontend` container is running
- Checks if `db` container is running

### 2. Service Connectivity Check
- Tests backend on port 8002 (`/ping_fast` endpoint)
- Tests frontend on port 3000

### 3. Nginx Status Check
- Verifies nginx is running
- Validates nginx configuration
- Checks nginx error logs for 502 errors

### 4. Automatic Fixes
- Starts Docker services if not running
- Restarts backend if container is running but not responding
- Restarts frontend if container is running but not responding
- Reloads nginx configuration
- Starts nginx if it's not running

### 5. Final Status Report
- Provides summary of all services
- Shows what's working and what's not
- Provides troubleshooting tips

## Prerequisites

1. **SSH Access**: You must have SSH access to the AWS server
2. **SSH Key**: The script uses `~/.ssh/id_rsa` by default (or set `SSH_KEY` env var)
3. **Sudo Access**: The remote user needs sudo access for nginx operations

## Common Issues

### Backend Not Responding
- Check Docker logs: `docker logs backend-aws`
- Verify port 8002 is not blocked by firewall
- Check if backend container is healthy: `docker ps --filter name=backend-aws`

### Frontend Not Responding
- Check Docker logs: `docker logs frontend`
- Verify port 3000 is not blocked by firewall
- Check if frontend container is healthy: `docker ps --filter name=frontend`

### Nginx Configuration Errors
- Test configuration: `sudo nginx -t`
- Check error logs: `sudo tail -f /var/log/nginx/error.log`
- Verify nginx can reach services: `curl http://localhost:8002/ping_fast`

## Related Scripts

- `scripts/diagnose-502.sh` - Local diagnostic tool
- `restart_nginx_aws.sh` - Quick nginx restart on AWS
- `scripts/start-aws-stack.sh` - Start all AWS services

## Troubleshooting

If the script doesn't fix the issue:

1. **Check Docker Compose Status**:
   ```bash
   ssh ubuntu@SERVER "cd ~/automated-trading-platform && docker compose --profile aws ps"
   ```

2. **Check Service Logs**:
   ```bash
   ssh ubuntu@SERVER "cd ~/automated-trading-platform && docker compose --profile aws logs --tail=50"
   ```

3. **Manual Service Start**:
   ```bash
   ssh ubuntu@SERVER "cd ~/automated-trading-platform && docker compose --profile aws up -d"
   ```

4. **Check Nginx Error Logs**:
   ```bash
   ssh ubuntu@SERVER "sudo tail -50 /var/log/nginx/error.log"
   ```

## Notes

- The script waits for services to stabilize after starting/restarting
- All operations are logged for debugging
- The script is idempotent - safe to run multiple times







