#!/bin/bash
# Backend Health Diagnostic and Fix Script
# This script diagnoses backend health issues and provides options to fix them

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
EC2_HOST="54.254.150.31"
EC2_USER="ubuntu"
BACKEND_PORT="8002"
PROJECT_DIR="~/automated-trading-platform"

# Load SSH key if available
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh 2>/dev/null || true

print_header() {
    echo -e "\n${CYAN}========================================${NC}"
    echo -e "${CYAN}$1${NC}"
    echo -e "${CYAN}========================================${NC}\n"
}

print_status() {
    echo -e "${GREEN}✅ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

print_error() {
    echo -e "${RED}❌ $1${NC}"
}

print_info() {
    echo -e "${BLUE}ℹ️  $1${NC}"
}

# Function to check if we're running on AWS server or locally
is_on_aws_server() {
    # Check if we're on the AWS server by hostname or IP
    if [ -f "/etc/cloud/cloud.cfg" ] || hostname | grep -q "ip-" || [ "$(curl -s http://169.254.169.254/latest/meta-data/instance-id 2>/dev/null)" != "" ]; then
        return 0
    fi
    return 1
}

# Main diagnostic function
diagnose_backend() {
    print_header "Backend Health Diagnostic"
    
    if is_on_aws_server; then
        print_info "Running diagnostics on AWS server..."
        run_local_diagnostics
    else
        print_info "Running diagnostics remotely via SSH..."
        run_remote_diagnostics
    fi
}

# Run diagnostics locally (on AWS server)
run_local_diagnostics() {
    cd ~/automated-trading-platform 2>/dev/null || cd /home/ubuntu/automated-trading-platform 2>/dev/null || {
        print_error "Cannot find project directory"
        exit 1
    }
    
    # Step 1: Check Docker Compose status
    print_header "Step 1: Checking Container Status"
    if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up"; then
        print_status "Backend container is running"
        docker compose --profile aws ps backend-aws
    else
        print_error "Backend container is NOT running"
        docker compose --profile aws ps backend-aws 2>/dev/null || echo "Container not found"
    fi
    
    # Step 2: Check container health
    print_header "Step 2: Checking Container Health"
    HEALTH_STATUS=$(docker compose --profile aws ps backend-aws 2>/dev/null | grep backend-aws | awk '{print $NF}' || echo "unknown")
    if echo "$HEALTH_STATUS" | grep -q "healthy"; then
        print_status "Container health: $HEALTH_STATUS"
    elif echo "$HEALTH_STATUS" | grep -q "unhealthy"; then
        print_warning "Container health: $HEALTH_STATUS"
    else
        print_warning "Container health: $HEALTH_STATUS"
    fi
    
    # Step 3: Test health endpoints
    print_header "Step 3: Testing Health Endpoints"
    
    # Test ping_fast
    print_info "Testing /ping_fast endpoint..."
    if curl -s -f --max-time 5 http://localhost:${BACKEND_PORT}/ping_fast > /dev/null 2>&1; then
        print_status "/ping_fast is responding"
    else
        print_error "/ping_fast is NOT responding"
    fi
    
    # Test /health
    print_info "Testing /health endpoint..."
    HEALTH_RESPONSE=$(curl -s --max-time 5 http://localhost:${BACKEND_PORT}/health 2>/dev/null || echo "")
    if [ -n "$HEALTH_RESPONSE" ]; then
        print_status "/health is responding"
        echo "$HEALTH_RESPONSE" | head -5
    else
        print_error "/health is NOT responding"
    fi
    
    # Test /api/monitoring/summary
    print_info "Testing /api/monitoring/summary endpoint..."
    MONITORING_RESPONSE=$(curl -s --max-time 10 http://localhost:${BACKEND_PORT}/api/monitoring/summary 2>/dev/null || echo "")
    if [ -n "$MONITORING_RESPONSE" ]; then
        BACKEND_HEALTH=$(echo "$MONITORING_RESPONSE" | grep -o '"backend_health":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
        print_status "/api/monitoring/summary is responding"
        print_info "Backend health status: $BACKEND_HEALTH"
        if [ "$BACKEND_HEALTH" = "error" ]; then
            print_error "Backend health is ERROR"
        elif [ "$BACKEND_HEALTH" = "unhealthy" ]; then
            print_warning "Backend health is UNHEALTHY"
        elif [ "$BACKEND_HEALTH" = "degraded" ]; then
            print_warning "Backend health is DEGRADED"
        elif [ "$BACKEND_HEALTH" = "healthy" ]; then
            print_status "Backend health is HEALTHY"
        fi
    else
        print_error "/api/monitoring/summary is NOT responding"
    fi
    
    # Step 4: Check recent logs
    print_header "Step 4: Recent Backend Logs (last 30 lines)"
    docker compose --profile aws logs --tail=30 backend-aws 2>/dev/null || print_warning "Could not retrieve logs"
    
    # Step 5: Check for errors in logs
    print_header "Step 5: Error Summary (last 100 lines)"
    ERROR_COUNT=$(docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | wc -l || echo "0")
    if [ "$ERROR_COUNT" -gt 0 ]; then
        print_warning "Found $ERROR_COUNT error/exception lines in recent logs"
        docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | tail -10
    else
        print_status "No recent errors found in logs"
    fi
    
    # Step 6: Check database connection
    print_header "Step 6: Checking Database Connection"
    if docker compose --profile aws ps db 2>/dev/null | grep -q "Up"; then
        print_status "Database container is running"
        if docker compose --profile aws exec -T db pg_isready -U trader 2>/dev/null > /dev/null; then
            print_status "Database is ready"
        else
            print_warning "Database may not be ready"
        fi
    else
        print_error "Database container is NOT running"
    fi
    
    # Step 7: Check port availability
    print_header "Step 7: Checking Port ${BACKEND_PORT}"
    if netstat -tuln 2>/dev/null | grep -q ":${BACKEND_PORT} " || ss -tuln 2>/dev/null | grep -q ":${BACKEND_PORT} "; then
        print_status "Port ${BACKEND_PORT} is in use"
        netstat -tuln 2>/dev/null | grep ":${BACKEND_PORT} " || ss -tuln 2>/dev/null | grep ":${BACKEND_PORT} "
    else
        print_error "Port ${BACKEND_PORT} is NOT in use (backend not listening)"
    fi
    
    # Summary
    print_header "Diagnostic Summary"
    if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up" && \
       curl -s -f --max-time 5 http://localhost:${BACKEND_PORT}/ping_fast > /dev/null 2>&1; then
        print_status "Backend appears to be running and responding"
        print_info "If dashboard still shows ERROR, try refreshing the page"
    else
        print_error "Backend is NOT running or NOT responding"
        print_info "Run this script with --fix flag to attempt automatic fix"
    fi
}

# Run diagnostics remotely (from local machine)
run_remote_diagnostics() {
    print_info "Connecting to AWS server: $EC2_USER@$EC2_HOST"
    
    if [ -n "$(type -t ssh_cmd)" ]; then
        ssh_cmd "$EC2_USER@$EC2_HOST" << 'DIAG_SCRIPT'
cd ~/automated-trading-platform

echo "=========================================="
echo "Backend Health Diagnostic"
echo "=========================================="
echo ""

# Step 1: Container status
echo "Step 1: Container Status"
if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up"; then
    echo "✅ Backend container is running"
    docker compose --profile aws ps backend-aws
else
    echo "❌ Backend container is NOT running"
    docker compose --profile aws ps backend-aws 2>/dev/null || echo "Container not found"
fi
echo ""

# Step 2: Health endpoints
echo "Step 2: Health Endpoints"
echo "Testing /ping_fast..."
if curl -s -f --max-time 5 http://localhost:8002/ping_fast > /dev/null 2>&1; then
    echo "✅ /ping_fast is responding"
else
    echo "❌ /ping_fast is NOT responding"
fi

echo "Testing /health..."
HEALTH_RESPONSE=$(curl -s --max-time 5 http://localhost:8002/health 2>/dev/null || echo "")
if [ -n "$HEALTH_RESPONSE" ]; then
    echo "✅ /health is responding"
    echo "$HEALTH_RESPONSE" | head -3
else
    echo "❌ /health is NOT responding"
fi

echo "Testing /api/monitoring/summary..."
MONITORING_RESPONSE=$(curl -s --max-time 10 http://localhost:8002/api/monitoring/summary 2>/dev/null || echo "")
if [ -n "$MONITORING_RESPONSE" ]; then
    BACKEND_HEALTH=$(echo "$MONITORING_RESPONSE" | grep -o '"backend_health":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    echo "✅ /api/monitoring/summary is responding"
    echo "Backend health: $BACKEND_HEALTH"
else
    echo "❌ /api/monitoring/summary is NOT responding"
fi
echo ""

# Step 3: Recent logs
echo "Step 3: Recent Logs (last 20 lines)"
docker compose --profile aws logs --tail=20 backend-aws 2>/dev/null || echo "Could not retrieve logs"
echo ""

# Step 4: Error summary
echo "Step 4: Error Summary"
ERROR_COUNT=$(docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | wc -l || echo "0")
echo "Found $ERROR_COUNT error/exception lines in recent logs"
if [ "$ERROR_COUNT" -gt 0 ]; then
    docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | tail -5
fi
echo ""

# Step 5: Database status
echo "Step 5: Database Status"
if docker compose --profile aws ps db 2>/dev/null | grep -q "Up"; then
    echo "✅ Database container is running"
else
    echo "❌ Database container is NOT running"
fi
echo ""

echo "=========================================="
echo "Diagnostic Complete"
echo "=========================================="
DIAG_SCRIPT
    else
        ssh "$EC2_USER@$EC2_HOST" << 'DIAG_SCRIPT'
cd ~/automated-trading-platform

echo "=========================================="
echo "Backend Health Diagnostic"
echo "=========================================="
echo ""

# Step 1: Container status
echo "Step 1: Container Status"
if docker compose --profile aws ps backend-aws 2>/dev/null | grep -q "Up"; then
    echo "✅ Backend container is running"
    docker compose --profile aws ps backend-aws
else
    echo "❌ Backend container is NOT running"
    docker compose --profile aws ps backend-aws 2>/dev/null || echo "Container not found"
fi
echo ""

# Step 2: Health endpoints
echo "Step 2: Health Endpoints"
echo "Testing /ping_fast..."
if curl -s -f --max-time 5 http://localhost:8002/ping_fast > /dev/null 2>&1; then
    echo "✅ /ping_fast is responding"
else
    echo "❌ /ping_fast is NOT responding"
fi

echo "Testing /health..."
HEALTH_RESPONSE=$(curl -s --max-time 5 http://localhost:8002/health 2>/dev/null || echo "")
if [ -n "$HEALTH_RESPONSE" ]; then
    echo "✅ /health is responding"
    echo "$HEALTH_RESPONSE" | head -3
else
    echo "❌ /health is NOT responding"
fi

echo "Testing /api/monitoring/summary..."
MONITORING_RESPONSE=$(curl -s --max-time 10 http://localhost:8002/api/monitoring/summary 2>/dev/null || echo "")
if [ -n "$MONITORING_RESPONSE" ]; then
    BACKEND_HEALTH=$(echo "$MONITORING_RESPONSE" | grep -o '"backend_health":"[^"]*"' | cut -d'"' -f4 || echo "unknown")
    echo "✅ /api/monitoring/summary is responding"
    echo "Backend health: $BACKEND_HEALTH"
else
    echo "❌ /api/monitoring/summary is NOT responding"
fi
echo ""

# Step 3: Recent logs
echo "Step 3: Recent Logs (last 20 lines)"
docker compose --profile aws logs --tail=20 backend-aws 2>/dev/null || echo "Could not retrieve logs"
echo ""

# Step 4: Error summary
echo "Step 4: Error Summary"
ERROR_COUNT=$(docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | wc -l || echo "0")
echo "Found $ERROR_COUNT error/exception lines in recent logs"
if [ "$ERROR_COUNT" -gt 0 ]; then
    docker compose --profile aws logs --tail=100 backend-aws 2>/dev/null | grep -i "error\|exception\|traceback\|failed" | tail -5
fi
echo ""

# Step 5: Database status
echo "Step 5: Database Status"
if docker compose --profile aws ps db 2>/dev/null | grep -q "Up"; then
    echo "✅ Database container is running"
else
    echo "❌ Database container is NOT running"
fi
echo ""

echo "=========================================="
echo "Diagnostic Complete"
echo "=========================================="
DIAG_SCRIPT
    fi
}

# Fix function
fix_backend() {
    print_header "Attempting to Fix Backend"
    
    if is_on_aws_server; then
        fix_local_backend
    else
        fix_remote_backend
    fi
}

# Fix backend locally
fix_local_backend() {
    cd ~/automated-trading-platform 2>/dev/null || cd /home/ubuntu/automated-trading-platform 2>/dev/null || {
        print_error "Cannot find project directory"
        exit 1
    }
    
    print_info "Restarting backend container..."
    docker compose --profile aws restart backend-aws
    
    print_info "Waiting 30 seconds for backend to start..."
    sleep 30
    
    print_info "Checking status..."
    docker compose --profile aws ps backend-aws
    
    print_info "Testing health endpoint..."
    if curl -s -f --max-time 10 http://localhost:${BACKEND_PORT}/ping_fast > /dev/null 2>&1; then
        print_status "Backend is now responding!"
    else
        print_warning "Backend may still be starting. Waiting another 30 seconds..."
        sleep 30
        if curl -s -f --max-time 10 http://localhost:${BACKEND_PORT}/ping_fast > /dev/null 2>&1; then
            print_status "Backend is now responding!"
        else
            print_error "Backend is still not responding. Check logs for errors."
            docker compose --profile aws logs --tail=50 backend-aws
        fi
    fi
}

# Fix backend remotely
fix_remote_backend() {
    print_info "Connecting to AWS server to restart backend..."
    
    if [ -n "$(type -t ssh_cmd)" ]; then
        ssh_cmd "$EC2_USER@$EC2_HOST" << 'FIX_SCRIPT'
cd ~/automated-trading-platform

echo "🔄 Restarting backend..."
docker compose --profile aws restart backend-aws

echo "⏳ Waiting 30 seconds for backend to start..."
sleep 30

echo "📊 Checking status..."
docker compose --profile aws ps backend-aws

echo ""
echo "🧪 Testing health endpoint..."
if curl -s -f --max-time 10 http://localhost:8002/ping_fast > /dev/null 2>&1; then
    echo "✅ Backend is now responding!"
else
    echo "⚠️  Backend may still be starting. Check logs:"
    docker compose --profile aws logs --tail=30 backend-aws
fi
FIX_SCRIPT
    else
        ssh "$EC2_USER@$EC2_HOST" << 'FIX_SCRIPT'
cd ~/automated-trading-platform

echo "🔄 Restarting backend..."
docker compose --profile aws restart backend-aws

echo "⏳ Waiting 30 seconds for backend to start..."
sleep 30

echo "📊 Checking status..."
docker compose --profile aws ps backend-aws

echo ""
echo "🧪 Testing health endpoint..."
if curl -s -f --max-time 10 http://localhost:8002/ping_fast > /dev/null 2>&1; then
    echo "✅ Backend is now responding!"
else
    echo "⚠️  Backend may still be starting. Check logs:"
    docker compose --profile aws logs --tail=30 backend-aws
fi
FIX_SCRIPT
    fi
}

# Main script logic
case "${1:-}" in
    --fix|-f)
        fix_backend
        ;;
    --help|-h)
        echo "Usage: $0 [OPTIONS]"
        echo ""
        echo "Options:"
        echo "  (no args)    Run diagnostics only"
        echo "  --fix, -f    Run diagnostics and attempt to fix"
        echo "  --help, -h   Show this help message"
        echo ""
        echo "This script can be run:"
        echo "  - Locally: Will SSH into AWS server and run diagnostics"
        echo "  - On AWS server: Will run diagnostics directly"
        ;;
    *)
        diagnose_backend
        echo ""
        print_info "To attempt automatic fix, run: $0 --fix"
        ;;
esac

