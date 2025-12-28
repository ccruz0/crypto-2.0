#!/bin/bash
# Backend Health Check and Fix Script
# Checks backend status on remote server and can start/restart it

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
EC2_HOST_PRIMARY="54.254.150.31"
EC2_HOST_ALTERNATIVE="175.41.189.249"
EC2_USER="ubuntu"
PROJECT_DIR="automated-trading-platform"
BACKEND_PORT="8002"

# Load SSH helpers
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

# Function to print colored output
print_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[⚠]${NC} $1"
}

print_error() {
    echo -e "${RED}[✗]${NC} $1"
}

print_header() {
    echo ""
    echo -e "${BLUE}========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}========================================${NC}"
    echo ""
}

# Determine which host to use
EC2_HOST=""
if ssh_cmd -o ConnectTimeout=5 "$EC2_USER@$EC2_HOST_PRIMARY" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_PRIMARY"
    print_success "Using primary host: $EC2_HOST"
elif ssh_cmd -o ConnectTimeout=5 "$EC2_USER@$EC2_HOST_ALTERNATIVE" "echo 'Connected'" > /dev/null 2>&1; then
    EC2_HOST="$EC2_HOST_ALTERNATIVE"
    print_success "Using alternative host: $EC2_HOST"
else
    print_error "Cannot connect to either host"
    print_warning "Tried: $EC2_HOST_PRIMARY and $EC2_HOST_ALTERNATIVE"
    exit 1
fi

# Main diagnostic and fix script
print_header "Backend Health Check and Fix"

# Step 1: Check if backend is running (Docker)
print_info "Step 1: Checking Docker backend status..."
DOCKER_STATUS=$(ssh_cmd "$EC2_USER@$EC2_HOST" "cd ~/$PROJECT_DIR && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q 'Up' && echo 'running' || echo 'stopped'" 2>/dev/null || echo "unknown")

if [ "$DOCKER_STATUS" = "running" ]; then
    print_success "Docker backend container is running"
    DOCKER_RUNNING=true
else
    print_warning "Docker backend container is not running"
    DOCKER_RUNNING=false
fi

# Step 2: Check if backend process is running (direct uvicorn)
print_info "Step 2: Checking direct backend process..."
PROCESS_STATUS=$(ssh_cmd "$EC2_USER@$EC2_HOST" "ps aux | grep -E 'uvicorn.*app.main:app.*port.*8002' | grep -v grep | wc -l" 2>/dev/null || echo "0")

if [ "$PROCESS_STATUS" -gt 0 ]; then
    print_success "Direct backend process is running"
    PROCESS_RUNNING=true
else
    print_warning "Direct backend process is not running"
    PROCESS_RUNNING=false
fi

# Step 3: Check if backend is accessible on port 8002
print_info "Step 3: Testing backend connectivity on port $BACKEND_PORT..."
HEALTH_CHECK=$(ssh_cmd "$EC2_USER@$EC2_HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$BACKEND_PORT/health 2>/dev/null || echo '000'" 2>/dev/null || echo "000")

if [ "$HEALTH_CHECK" = "200" ]; then
    print_success "Backend is accessible on port $BACKEND_PORT (HTTP $HEALTH_CHECK)"
    BACKEND_ACCESSIBLE=true
else
    print_error "Backend is NOT accessible on port $BACKEND_PORT (HTTP $HEALTH_CHECK)"
    BACKEND_ACCESSIBLE=false
fi

# Step 4: Check nginx connectivity
print_info "Step 4: Testing nginx -> backend connection..."
NGINX_CHECK=$(ssh_cmd "$EC2_USER@$EC2_HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$BACKEND_PORT/api/monitoring/summary 2>/dev/null || echo '000'" 2>/dev/null || echo "000")

if [ "$NGINX_CHECK" = "200" ]; then
    print_success "Nginx can reach backend API (HTTP $NGINX_CHECK)"
    NGINX_ACCESSIBLE=true
else
    print_warning "Nginx cannot reach backend API (HTTP $NGINX_CHECK)"
    NGINX_ACCESSIBLE=false
fi

# Step 5: Check external access through nginx
print_info "Step 5: Testing external access through nginx..."
EXTERNAL_CHECK=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://dashboard.hilovivo.com/api/monitoring/summary" 2>/dev/null || echo "000")

if [ "$EXTERNAL_CHECK" = "200" ]; then
    print_success "External access through nginx is working (HTTP $EXTERNAL_CHECK)"
    EXTERNAL_ACCESSIBLE=true
else
    print_error "External access through nginx is NOT working (HTTP $EXTERNAL_CHECK)"
    EXTERNAL_ACCESSIBLE=false
fi

# Summary
print_header "Status Summary"
echo "Docker Backend:     $([ "$DOCKER_RUNNING" = true ] && echo -e "${GREEN}Running${NC}" || echo -e "${RED}Stopped${NC}")"
echo "Direct Process:     $([ "$PROCESS_RUNNING" = true ] && echo -e "${GREEN}Running${NC}" || echo -e "${RED}Stopped${NC}")"
echo "Backend Accessible: $([ "$BACKEND_ACCESSIBLE" = true ] && echo -e "${GREEN}Yes${NC}" || echo -e "${RED}No${NC}")"
echo "Nginx Accessible:   $([ "$NGINX_ACCESSIBLE" = true ] && echo -e "${GREEN}Yes${NC}" || echo -e "${RED}No${NC}")"
echo "External Access:    $([ "$EXTERNAL_ACCESSIBLE" = true ] && echo -e "${GREEN}Yes${NC}" || echo -e "${RED}No${NC}")"
echo ""

# If backend is not accessible, offer to fix it
if [ "$BACKEND_ACCESSIBLE" = false ] || [ "$EXTERNAL_ACCESSIBLE" = false ]; then
    print_warning "Backend is not accessible. Would you like to start/restart it?"
    echo ""
    echo "Options:"
    echo "  1) Start Docker backend (recommended)"
    echo "  2) Start direct uvicorn process"
    echo "  3) Restart Docker backend"
    echo "  4) Check logs only"
    echo "  5) Exit"
    echo ""
    read -p "Enter choice [1-5]: " choice
    
    case $choice in
        1)
            print_info "Starting Docker backend..."
            ssh_cmd "$EC2_USER@$EC2_HOST" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose --profile aws up -d backend-aws
sleep 5
docker compose --profile aws ps backend-aws
ENDSSH
            print_success "Docker backend start command executed"
            ;;
        2)
            print_info "Starting direct uvicorn process..."
            ssh_cmd "$EC2_USER@$EC2_HOST" << 'ENDSSH'
cd ~/automated-trading-platform/backend
# Stop any existing process
pkill -f "uvicorn.*app.main:app.*port.*8002" || true
sleep 2
# Start in background
nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002 > backend.log 2>&1 &
sleep 3
# Check if it started
ps aux | grep -E "uvicorn.*app.main:app.*port.*8002" | grep -v grep
ENDSSH
            print_success "Direct backend start command executed"
            ;;
        3)
            print_info "Restarting Docker backend..."
            ssh_cmd "$EC2_USER@$EC2_HOST" << 'ENDSSH'
cd ~/automated-trading-platform
docker compose --profile aws restart backend-aws
sleep 5
docker compose --profile aws ps backend-aws
ENDSSH
            print_success "Docker backend restart command executed"
            ;;
        4)
            print_info "Checking backend logs..."
            ssh_cmd "$EC2_USER@$EC2_HOST" << 'ENDSSH'
cd ~/automated-trading-platform
echo "=== Docker Backend Logs (last 30 lines) ==="
docker compose --profile aws logs --tail=30 backend-aws 2>/dev/null || echo "No Docker logs available"
echo ""
echo "=== Direct Process Logs (if exists) ==="
tail -30 ~/automated-trading-platform/backend/backend.log 2>/dev/null || echo "No process logs available"
ENDSSH
            ;;
        5)
            print_info "Exiting without changes"
            exit 0
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
    
    # Wait a bit and re-check
    echo ""
    print_info "Waiting 5 seconds and re-checking status..."
    sleep 5
    
    NEW_HEALTH=$(ssh_cmd "$EC2_USER@$EC2_HOST" "curl -s -o /dev/null -w '%{http_code}' --max-time 5 http://localhost:$BACKEND_PORT/health 2>/dev/null || echo '000'" 2>/dev/null || echo "000")
    
    if [ "$NEW_HEALTH" = "200" ]; then
        print_success "Backend is now accessible! (HTTP $NEW_HEALTH)"
        
        # Test external access again
        sleep 2
        NEW_EXTERNAL=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://dashboard.hilovivo.com/api/monitoring/summary" 2>/dev/null || echo "000")
        if [ "$NEW_EXTERNAL" = "200" ]; then
            print_success "External access is now working! (HTTP $NEW_EXTERNAL)"
        else
            print_warning "Backend is running but external access still shows HTTP $NEW_EXTERNAL"
            print_info "This might be a caching issue. Try refreshing the dashboard in a few seconds."
        fi
    else
        print_error "Backend is still not accessible (HTTP $NEW_HEALTH)"
        print_info "Check the logs above for errors"
    fi
else
    print_success "Backend is healthy and accessible!"
fi

echo ""
print_info "Script completed"










