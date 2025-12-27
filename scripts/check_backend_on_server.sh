#!/bin/bash
# Backend Health Check Script (to be run ON the server)
# This script checks backend status and can start/restart it

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
print_success() { echo -e "${GREEN}[✓]${NC} $1"; }
print_warning() { echo -e "${YELLOW}[⚠]${NC} $1"; }
print_error() { echo -e "${RED}[✗]${NC} $1"; }

PROJECT_DIR="${HOME}/automated-trading-platform"
BACKEND_PORT="8002"

echo ""
echo "=========================================="
echo "Backend Health Check"
echo "=========================================="
echo ""

# Check Docker backend
print_info "Checking Docker backend..."
if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up"; then
    print_success "Docker backend is running"
    DOCKER_RUNNING=true
    docker compose --profile aws ps backend-aws
else
    print_warning "Docker backend is not running"
    DOCKER_RUNNING=false
fi

echo ""

# Check direct process
print_info "Checking direct backend process..."
PROCESS_COUNT=$(ps aux | grep -E "uvicorn.*app.main:app.*port.*8002" | grep -v grep | wc -l)
if [ "$PROCESS_COUNT" -gt 0 ]; then
    print_success "Direct backend process is running"
    ps aux | grep -E "uvicorn.*app.main:app.*port.*8002" | grep -v grep
    PROCESS_RUNNING=true
else
    print_warning "Direct backend process is not running"
    PROCESS_RUNNING=false
fi

echo ""

# Check backend health
print_info "Testing backend health endpoint..."
HEALTH_RESPONSE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${BACKEND_PORT}/health" 2>/dev/null || echo "000")
if [ "$HEALTH_RESPONSE" = "200" ]; then
    print_success "Backend health check: OK (HTTP $HEALTH_RESPONSE)"
    HEALTH_OK=true
else
    print_error "Backend health check: FAILED (HTTP $HEALTH_RESPONSE)"
    HEALTH_OK=false
fi

echo ""

# Check monitoring endpoint
print_info "Testing monitoring endpoint..."
MONITORING_RESPONSE=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${BACKEND_PORT}/api/monitoring/summary" 2>/dev/null || echo "000")
if [ "$MONITORING_RESPONSE" = "200" ]; then
    print_success "Monitoring endpoint: OK (HTTP $MONITORING_RESPONSE)"
    MONITORING_OK=true
else
    print_error "Monitoring endpoint: FAILED (HTTP $MONITORING_RESPONSE)"
    MONITORING_OK=false
fi

echo ""
echo "=========================================="
echo "Summary"
echo "=========================================="
echo "Docker Backend:     $([ "$DOCKER_RUNNING" = true ] && echo -e "${GREEN}Running${NC}" || echo -e "${RED}Stopped${NC}")"
echo "Direct Process:     $([ "$PROCESS_RUNNING" = true ] && echo -e "${GREEN}Running${NC}" || echo -e "${RED}Stopped${NC}")"
echo "Health Endpoint:    $([ "$HEALTH_OK" = true ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAILED${NC}")"
echo "Monitoring Endpoint: $([ "$MONITORING_OK" = true ] && echo -e "${GREEN}OK${NC}" || echo -e "${RED}FAILED${NC}")"
echo ""

# If not healthy, offer to fix
if [ "$HEALTH_OK" = false ] || [ "$MONITORING_OK" = false ]; then
    echo "Backend is not healthy. Options:"
    echo "  1) Start Docker backend"
    echo "  2) Start direct uvicorn process"
    echo "  3) Restart Docker backend"
    echo "  4) View logs"
    echo "  5) Exit"
    echo ""
    read -p "Enter choice [1-5]: " choice
    
    case $choice in
        1)
            print_info "Starting Docker backend..."
            cd "$PROJECT_DIR"
            docker compose --profile aws up -d backend-aws
            sleep 5
            docker compose --profile aws ps backend-aws
            ;;
        2)
            print_info "Starting direct uvicorn process..."
            cd "$PROJECT_DIR/backend"
            pkill -f "uvicorn.*app.main:app.*port.*8002" || true
            sleep 2
            nohup python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8002 > backend.log 2>&1 &
            sleep 3
            ps aux | grep -E "uvicorn.*app.main:app.*port.*8002" | grep -v grep
            ;;
        3)
            print_info "Restarting Docker backend..."
            cd "$PROJECT_DIR"
            docker compose --profile aws restart backend-aws
            sleep 5
            docker compose --profile aws ps backend-aws
            ;;
        4)
            print_info "Backend logs:"
            cd "$PROJECT_DIR"
            echo "=== Docker Backend Logs (last 50 lines) ==="
            docker compose --profile aws logs --tail=50 backend-aws 2>/dev/null || echo "No Docker logs"
            echo ""
            echo "=== Direct Process Logs (if exists) ==="
            tail -50 "$PROJECT_DIR/backend/backend.log" 2>/dev/null || echo "No process logs"
            ;;
        5)
            print_info "Exiting"
            exit 0
            ;;
        *)
            print_error "Invalid choice"
            exit 1
            ;;
    esac
    
    echo ""
    print_info "Re-checking health..."
    sleep 3
    NEW_HEALTH=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "http://localhost:${BACKEND_PORT}/health" 2>/dev/null || echo "000")
    if [ "$NEW_HEALTH" = "200" ]; then
        print_success "Backend is now healthy! (HTTP $NEW_HEALTH)"
    else
        print_error "Backend is still not healthy (HTTP $NEW_HEALTH)"
    fi
else
    print_success "Backend is healthy and running!"
fi

echo ""







