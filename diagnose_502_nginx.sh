#!/bin/bash

# Comprehensive 502 Nginx Diagnostic Script
# Collects diagnostics and generates a Cursor prompt with fixes

set -euo pipefail

# Configuration
SSH_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"
LOCAL_PATH="/Users/carloscruz/automated-trading-platform"
LOG_DIR="$HOME/Desktop/atp-502-audit-logs"
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
LOG_FOLDER="$LOG_DIR/$TIMESTAMP"
LOG_FILE="$LOG_FOLDER/diagnostic.log"
PROMPT_FILE="$LOG_FOLDER/cursor_prompt_fix_502.md"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Create log directory
mkdir -p "$LOG_FOLDER"

# Logging function that writes to both file and terminal
log() {
    local level="$1"
    shift
    local message="$*"
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "[$timestamp] [$level] $message" | tee -a "$LOG_FILE"
}

log_info() {
    log "INFO" "${CYAN}$*${NC}"
}

log_success() {
    log "SUCCESS" "${GREEN}$*${NC}"
}

log_warning() {
    log "WARNING" "${YELLOW}$*${NC}"
}

log_error() {
    log "ERROR" "${RED}$*${NC}"
}

# Timeout wrapper function
run_with_timeout() {
    local timeout_sec="$1"
    shift
    local cmd="$*"
    
    if command -v gtimeout &> /dev/null; then
        gtimeout "$timeout_sec" bash -c "$cmd" || return $?
    elif command -v timeout &> /dev/null; then
        timeout "$timeout_sec" bash -c "$cmd" || return $?
    else
        # Fallback: run in background and kill after timeout
        local pid_file="/tmp/diagnose_502_$$.pid"
        bash -c "$cmd" &
        local pid=$!
        echo $pid > "$pid_file"
        
        # Wait for timeout or completion
        local count=0
        while [ $count -lt $timeout_sec ]; do
            if ! kill -0 $pid 2>/dev/null; then
                wait $pid
                rm -f "$pid_file"
                return $?
            fi
            sleep 1
            count=$((count + 1))
        done
        
        # Timeout reached
        kill $pid 2>/dev/null || true
        rm -f "$pid_file"
        log_error "Command timed out after ${timeout_sec}s: $cmd"
        return 124
    fi
}

# SSH command with proper options
ssh_cmd() {
    local cmd="$1"
    ssh -o BatchMode=yes \
        -o ConnectTimeout=10 \
        -o ServerAliveInterval=10 \
        -o ServerAliveCountMax=2 \
        -o StrictHostKeyChecking=no \
        "$SSH_HOST" "cd $REMOTE_PATH && $cmd" 2>&1 || {
        log_warning "SSH command failed: $cmd"
        return 1
    }
}

# Collect local diagnostics
collect_local_diagnostics() {
    log_info "=== Collecting Local Diagnostics ==="
    
    cd "$LOCAL_PATH" || {
        log_error "Failed to cd to $LOCAL_PATH"
        return 1
    }
    
    # Git commit
    log_info "Getting git commit..."
    {
        echo "=== Git Commit ==="
        git rev-parse HEAD 2>&1 || echo "ERROR: git rev-parse failed"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Docker compose status
    log_info "Checking Docker Compose status..."
    {
        echo "=== Docker Compose Status ==="
        docker compose ps 2>&1 || echo "ERROR: docker compose ps failed"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Backend logs
    log_info "Collecting backend logs..."
    {
        echo "=== Backend Logs (last 200 lines) ==="
        docker compose logs -n 200 backend-aws 2>&1 || echo "ERROR: backend logs not available"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Frontend logs
    log_info "Collecting frontend logs..."
    {
        echo "=== Frontend Logs (last 200 lines) ==="
        docker compose logs -n 200 frontend-aws 2>&1 || echo "ERROR: frontend logs not available"
        echo ""
    } | tee -a "$LOG_FILE"
}

# Collect remote diagnostics
collect_remote_diagnostics() {
    log_info "=== Collecting Remote Diagnostics ==="
    
    # Test SSH connection first
    log_info "Testing SSH connection..."
    if ! ssh_cmd "echo 'SSH connection successful'" > /dev/null 2>&1; then
        log_error "Cannot connect to $SSH_HOST. Skipping remote diagnostics."
        return 1
    fi
    log_success "SSH connection established"
    
    # Docker compose status
    log_info "Checking remote Docker Compose status..."
    {
        echo "=== Remote Docker Compose Status ==="
        ssh_cmd "docker compose --profile aws ps" || echo "ERROR: docker compose ps failed"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Backend logs
    log_info "Collecting remote backend logs..."
    {
        echo "=== Remote Backend Logs (last 300 lines) ==="
        ssh_cmd "docker compose --profile aws logs -n 300 backend-aws" || echo "ERROR: backend logs not available"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Nginx logs
    log_info "Collecting nginx logs..."
    {
        echo "=== Nginx Logs (last 300 lines) ==="
        ssh_cmd "docker compose --profile aws logs -n 300 nginx" || \
        ssh_cmd "docker compose --profile aws logs -n 300 frontend-aws" || \
        echo "WARNING: nginx logs not found in docker compose"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Nginx config test
    log_info "Testing nginx configuration..."
    {
        echo "=== Nginx Config Test ==="
        ssh_cmd "docker compose --profile aws exec -T nginx nginx -t 2>&1" || \
        ssh_cmd "docker compose --profile aws exec -T frontend-aws nginx -t 2>&1" || \
        echo "WARNING: nginx config test not available"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Check uvicorn/gunicorn command
    log_info "Checking backend process command..."
    {
        echo "=== Backend Process Command ==="
        ssh_cmd "docker compose --profile aws exec -T backend-aws ps aux | grep -E 'uvicorn|gunicorn' | head -5" || \
        ssh_cmd "docker compose --profile aws inspect backend-aws | grep -A 10 -B 10 'Cmd\|Command' | head -20" || \
        echo "WARNING: Could not determine backend command"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Check for --reload flag
    log_info "Checking for --reload flag in production..."
    {
        echo "=== Checking for --reload in Production ==="
        ssh_cmd "docker compose --profile aws exec -T backend-aws ps aux | grep -E '--reload' && echo '⚠️  WARNING: --reload found in production!' || echo '✓ No --reload flag found'"
        echo ""
    } | tee -a "$LOG_FILE"
    
    # Nginx access/error logs (best effort)
    log_info "Collecting nginx access/error logs (best effort)..."
    {
        echo "=== Nginx Access/Error Logs (last 200 lines) ==="
        ssh_cmd "sudo tail -200 /var/log/nginx/access.log 2>/dev/null || docker compose --profile aws exec -T nginx tail -200 /var/log/nginx/access.log 2>/dev/null || echo 'Access log not available'" || true
        echo ""
        ssh_cmd "sudo tail -200 /var/log/nginx/error.log 2>/dev/null || docker compose --profile aws exec -T nginx tail -200 /var/log/nginx/error.log 2>/dev/null || echo 'Error log not available'" || true
        echo ""
    } | tee -a "$LOG_FILE"
}

# Analyze diagnostics and generate Cursor prompt
generate_cursor_prompt() {
    log_info "=== Generating Cursor Prompt ==="
    
    local log_content=$(cat "$LOG_FILE")
    
    # Analyze for common issues
    local issues=()
    local fixes=()
    local evidence=()
    
    # Check for --reload in production
    if echo "$log_content" | grep -q "WARNING: --reload found in production"; then
        issues+=("uvicorn running with --reload in production")
        fixes+=("Remove --reload flag from production docker-compose.yml or startup command")
        evidence+=("Found '--reload' flag in backend process command")
    fi
    
    # Check for nginx errors
    if echo "$log_content" | grep -qi "502\|bad gateway\|upstream\|timeout" "$LOG_FILE"; then
        issues+=("Nginx 502 errors detected")
        fixes+=("Check nginx upstream timeouts and backend health")
        evidence+=("Found 502/bad gateway/timeout in logs")
    fi
    
    # Check backend status
    if echo "$log_content" | grep -qi "backend-aws.*Exit\|backend-aws.*unhealthy"; then
        issues+=("Backend container unhealthy or exited")
        fixes+=("Check backend logs and restart if needed")
        evidence+=("Backend container status shows Exit or unhealthy")
    fi
    
    # Generate the prompt file
    cat > "$PROMPT_FILE" << EOF
# Fix 502 Nginx Error - Root Cause Analysis and Solution

## Summary

This diagnostic was run on $(date) to troubleshoot recurring 502 errors in the Nginx gateway.

## Diagnostic Evidence

### Issues Found

$(for i in "${!issues[@]}"; do
    echo "$((i+1)). **${issues[$i]}**"
    echo "   - Evidence: ${evidence[$i]}"
    echo ""
done)

### Log File Location
\`\`\`
$LOG_FILE
\`\`\`

## Root Cause Analysis

Based on the diagnostic logs, the likely root cause is:

$(if [ ${#issues[@]} -gt 0 ]; then
    echo "- **Primary Issue**: ${issues[0]}"
    echo ""
    echo "This is causing Nginx to return 502 Bad Gateway errors when trying to proxy requests to the backend."
else
    echo "- Review the diagnostic logs in $LOG_FILE for specific error patterns"
fi)

## Required Code Changes

### 1. Remove --reload from Production

**File**: \`docker-compose.yml\` or backend startup script

**Change**:
\`\`\`yaml
# BEFORE (if found):
command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# AFTER:
command: uvicorn app.main:app --host 0.0.0.0 --port 8000
# OR use gunicorn for production:
command: gunicorn app.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
\`\`\`

### 2. Add Health Checks

**File**: \`docker-compose.yml\`

**Add to backend-aws service**:
\`\`\`yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
\`\`\`

### 3. Fix Nginx Upstream Timeouts

**File**: \`nginx/dashboard.conf\`

**Ensure these settings exist**:
\`\`\`nginx
upstream backend {
    server backend-aws:8000;
    keepalive 32;
}

server {
    # ... existing config ...
    
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
    proxy_buffering off;
    
    location / {
        proxy_pass http://backend;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }
}
\`\`\`

## Verification Steps

1. **Deploy the changes**:
   \`\`\`bash
   cd $REMOTE_PATH
   git add .
   git commit -m "Fix 502: Remove --reload, add healthchecks, fix nginx timeouts"
   git push
   # Then deploy to AWS
   \`\`\`

2. **Test the endpoint**:
   \`\`\`bash
   curl -v https://dashboard.hilovivo.com/api/health
   \`\`\`

3. **Monitor for 502 errors**:
   \`\`\`bash
   ssh $SSH_HOST "sudo tail -f /var/log/nginx/error.log | grep 502"
   \`\`\`

4. **Check backend health**:
   \`\`\`bash
   ssh $SSH_HOST "cd $REMOTE_PATH && docker compose --profile aws ps backend-aws"
   \`\`\`

## Deployment Steps

1. Make the code changes above
2. Commit and push:
   \`\`\`bash
   cd $LOCAL_PATH
   git add docker-compose.yml nginx/dashboard.conf
   git commit -m "Fix 502: Remove --reload, add healthchecks, fix nginx timeouts"
   git push
   \`\`\`

3. Deploy to AWS (use your deployment method)

4. Restart services:
   \`\`\`bash
   ssh $SSH_HOST "cd $REMOTE_PATH && docker compose --profile aws restart backend-aws && sudo systemctl restart nginx"
   \`\`\`

## Expected Outcome

After applying these fixes:
- ✅ No more 502 errors
- ✅ Backend stays healthy
- ✅ Nginx properly proxies requests
- ✅ Health checks ensure backend is ready before accepting traffic

---

*Generated by diagnose_502_nginx.sh on $(date)*
EOF

    log_success "Cursor prompt generated: $PROMPT_FILE"
    
    # Copy to clipboard
    if command -v pbcopy &> /dev/null; then
        cat "$PROMPT_FILE" | pbcopy
        log_success "Prompt copied to clipboard"
    fi
}

# Main execution
main() {
    log_info "=========================================="
    log_info "502 Nginx Diagnostic Script"
    log_info "=========================================="
    log_info ""
    log_info "Log folder: $LOG_FOLDER"
    log_info "Log file: $LOG_FILE"
    log_info ""
    
    # Collect diagnostics
    collect_local_diagnostics || log_warning "Some local diagnostics failed"
    
    log_info ""
    collect_remote_diagnostics || log_warning "Some remote diagnostics failed"
    
    log_info ""
    generate_cursor_prompt
    
    log_info ""
    log_success "=========================================="
    log_success "Diagnostic Complete"
    log_success "=========================================="
    log_info ""
    log_info "Log file: $LOG_FILE"
    log_info "Cursor prompt: $PROMPT_FILE"
    log_info ""
    log_success "DONE"
}

# Run main function
main "$@"







