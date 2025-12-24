#!/bin/bash

# Auto-restart script for Docker containers on AWS
# This script checks if containers are running and restarts them if needed
# Can be run as a cron job (e.g., every 5 minutes)
# Can also be run remotely via SSH or locally on the server

REMOTE_PATH="/home/ubuntu/automated-trading-platform"
LOG_FILE="/tmp/auto_restart_containers.log"

# Check if running on the server (no SSH needed) or remotely
if [ -d "$REMOTE_PATH" ]; then
    # Running directly on the server
    RUN_MODE="local"
    cd "$REMOTE_PATH" || exit 1
else
    # Running remotely, need SSH
    SSH_HOST="hilovivo-aws"
    RUN_MODE="remote"
fi

# Colors for output (if running interactively)
if [ -t 1 ]; then
    RED='\033[0;31m'
    GREEN='\033[0;32m'
    YELLOW='\033[1;33m'
    CYAN='\033[0;36m'
    NC='\033[0m'
else
    RED=''
    GREEN=''
    YELLOW=''
    CYAN=''
    NC=''
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Function to run commands (local or via SSH)
run_cmd() {
    if [ "$RUN_MODE" = "local" ]; then
        eval "$@" 2>&1
    else
        ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "cd $REMOTE_PATH && $@" 2>&1
    fi
}

log "${CYAN}=== Checking container status ===${NC}"

# Check if containers are running
BACKEND_STATUS=$(run_cmd "docker compose --profile aws ps backend-aws --format json 2>/dev/null | grep -q '\"State\":\"running\"' && echo 'running' || echo 'stopped'")
FRONTEND_STATUS=$(run_cmd "docker compose --profile aws ps frontend-aws --format json 2>/dev/null | grep -q '\"State\":\"running\"' && echo 'running' || echo 'stopped'")

RESTART_NEEDED=false

# Check backend
if [ "$BACKEND_STATUS" != "running" ]; then
    log "${YELLOW}⚠ Backend container is not running${NC}"
    RESTART_NEEDED=true
else
    # Verify it's actually responding
    if [ "$RUN_MODE" = "local" ]; then
        BACKEND_HEALTH=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/health 2>/dev/null || echo '000')
    else
        BACKEND_HEALTH=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/health 2>/dev/null || echo '000'")
    fi
    
    if [ "$BACKEND_HEALTH" != "200" ]; then
        log "${YELLOW}⚠ Backend container is running but not healthy (HTTP $BACKEND_HEALTH)${NC}"
        RESTART_NEEDED=true
    else
        log "${GREEN}✓ Backend is running and healthy${NC}"
    fi
fi

# Check frontend
if [ "$FRONTEND_STATUS" != "running" ]; then
    log "${YELLOW}⚠ Frontend container is not running${NC}"
    RESTART_NEEDED=true
else
    # Verify it's actually responding
    if [ "$RUN_MODE" = "local" ]; then
        FRONTEND_HEALTH=$(curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null || echo '000')
    else
        FRONTEND_HEALTH=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null || echo '000'")
    fi
    
    if [ "$FRONTEND_HEALTH" != "200" ]; then
        log "${YELLOW}⚠ Frontend container is running but not healthy (HTTP $FRONTEND_HEALTH)${NC}"
        RESTART_NEEDED=true
    else
        log "${GREEN}✓ Frontend is running and healthy${NC}"
    fi
fi

# Restart if needed
if [ "$RESTART_NEEDED" = true ]; then
    log "${CYAN}Restarting containers...${NC}"
    
    # Start all services
    RESTART_OUTPUT=$(run_cmd "docker compose --profile aws up -d backend-aws frontend-aws 2>&1")
    
    if echo "$RESTART_OUTPUT" | grep -q "error\|Error\|ERROR\|failed\|Failed\|FAILED"; then
        log "${RED}❌ Error restarting containers:${NC}"
        echo "$RESTART_OUTPUT" | tee -a "$LOG_FILE"
        exit 1
    else
        log "${GREEN}✓ Containers restart initiated${NC}"
        
        # Wait a bit for containers to start
        sleep 10
        
        # Verify they're starting
        FINAL_BACKEND=$(run_cmd "docker compose --profile aws ps backend-aws --format '{{.Status}}' 2>/dev/null")
        FINAL_FRONTEND=$(run_cmd "docker compose --profile aws ps frontend-aws --format '{{.Status}}' 2>/dev/null")
        
        log "Backend status: $FINAL_BACKEND"
        log "Frontend status: $FINAL_FRONTEND"
        
        if echo "$FINAL_BACKEND" | grep -q "Up\|healthy" && echo "$FINAL_FRONTEND" | grep -q "Up\|healthy"; then
            log "${GREEN}✓ Containers are starting up${NC}"
        else
            log "${YELLOW}⚠ Containers may need more time to become healthy${NC}"
        fi
    fi
else
    log "${GREEN}✓ All containers are running properly${NC}"
fi

log "${CYAN}=== Check complete ===${NC}"
