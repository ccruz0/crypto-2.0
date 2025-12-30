#!/usr/bin/env bash
# Comprehensive script to diagnose and fix 502 Bad Gateway errors on AWS server
# Usage: ./scripts/fix-502-aws.sh [SERVER_IP]

set -e

# Load unified SSH helper
. "$(dirname "$0")/ssh_key.sh" 2>/dev/null || source "$(dirname "$0")/ssh_key.sh"

# Configuration
SERVER="${1:-47.130.143.159}"
EC2_USER="ubuntu"
REMOTE_PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/ubuntu/automated-trading-platform}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

banner() {
    echo ""
    echo "============================================================"
    echo -e "${BLUE}$@${NC}"
    echo "============================================================"
    echo ""
}

step() {
    echo -e "${BLUE}➡️  $@${NC}"
}

ok() {
    echo -e "${GREEN}✅ $@${NC}"
}

warn() {
    echo -e "${YELLOW}⚠️  $@${NC}"
}

err() {
    echo -e "${RED}❌ $@${NC}"
}

info() {
    echo -e "${BLUE}ℹ️  $@${NC}"
}

banner "502 Bad Gateway Diagnostic & Fix Tool"
info "Server: ${EC2_USER}@${SERVER}"
info "Project: ${REMOTE_PROJECT_DIR}"

# Test SSH connection
step "Testing SSH connection..."
if ssh_cmd "${EC2_USER}@${SERVER}" "echo 'SSH OK'" > /dev/null 2>&1; then
    ok "SSH connection successful"
else
    err "Cannot connect to ${EC2_USER}@${SERVER}"
    exit 1
fi

# Execute diagnostic and fix on remote server
ssh_cmd "${EC2_USER}@${SERVER}" "export REMOTE_PROJECT_DIR='${REMOTE_PROJECT_DIR}' && bash -s" << 'REMOTE_SCRIPT'
set -e

PROJECT_DIR="${REMOTE_PROJECT_DIR:-/home/ubuntu/automated-trading-platform}"

echo ""
echo "============================================================"
echo "1. CHECKING DOCKER SERVICES"
echo "============================================================"
echo ""

# Check if Docker is running
if ! docker ps > /dev/null 2>&1; then
    echo "❌ Docker is not running or not accessible"
    echo "💡 Starting Docker..."
    sudo systemctl start docker || true
    sleep 2
else
    echo "✅ Docker is running"
fi

# Check backend container
echo ""
echo "Checking backend-aws container..."
BACKEND_CONTAINER=$(docker ps --filter "name=backend-aws" --format "{{.Names}}" | head -1)
if [ -z "$BACKEND_CONTAINER" ]; then
    echo "❌ Backend container is NOT running"
    BACKEND_RUNNING=false
else
    echo "✅ Backend container is running: $BACKEND_CONTAINER"
    echo "   Status: $(docker ps --filter "name=backend-aws" --format "{{.Status}}")"
    BACKEND_RUNNING=true
fi

# Check frontend container
echo ""
echo "Checking frontend container..."
FRONTEND_CONTAINER=$(docker ps --filter "name=frontend" --format "{{.Names}}" | head -1)
if [ -z "$FRONTEND_CONTAINER" ]; then
    echo "❌ Frontend container is NOT running"
    FRONTEND_RUNNING=false
else
    echo "✅ Frontend container is running: $FRONTEND_CONTAINER"
    echo "   Status: $(docker ps --filter "name=frontend" --format "{{.Status}}")"
    FRONTEND_RUNNING=true
fi

# Check database container
echo ""
echo "Checking database container..."
DB_CONTAINER=$(docker ps --filter "name=db" --format "{{.Names}}" | head -1)
if [ -z "$DB_CONTAINER" ]; then
    echo "⚠️  Database container is NOT running"
    DB_RUNNING=false
else
    echo "✅ Database container is running: $DB_CONTAINER"
    DB_RUNNING=true
fi

echo ""
echo "============================================================"
echo "2. CHECKING SERVICE CONNECTIVITY"
echo "============================================================"
echo ""

# Check backend port 8002
echo "Testing backend on port 8002..."
if curl -s -f --connect-timeout 3 http://localhost:8002/ping_fast > /dev/null 2>&1; then
    BACKEND_RESPONSE=$(curl -s http://localhost:8002/ping_fast)
    echo "✅ Backend is responding: $BACKEND_RESPONSE"
    BACKEND_ACCESSIBLE=true
else
    echo "❌ Backend is NOT responding on port 8002"
    BACKEND_ACCESSIBLE=false
fi

# Check frontend port 3000
echo ""
echo "Testing frontend on port 3000..."
if curl -s -f --connect-timeout 3 http://localhost:3000 > /dev/null 2>&1; then
    echo "✅ Frontend is responding on port 3000"
    FRONTEND_ACCESSIBLE=true
else
    echo "❌ Frontend is NOT responding on port 3000"
    FRONTEND_ACCESSIBLE=false
fi

echo ""
echo "============================================================"
echo "3. CHECKING NGINX STATUS"
echo "============================================================"
echo ""

# Check nginx status
if systemctl is-active --quiet nginx 2>/dev/null || pgrep -x nginx > /dev/null; then
    echo "✅ Nginx is running"
    NGINX_RUNNING=true
else
    echo "❌ Nginx is NOT running"
    NGINX_RUNNING=false
fi

# Check nginx configuration
echo ""
echo "Testing nginx configuration..."
if sudo nginx -t 2>&1 | grep -q "syntax is ok"; then
    echo "✅ Nginx configuration is valid"
    NGINX_CONFIG_OK=true
else
    echo "❌ Nginx configuration has errors:"
    sudo nginx -t 2>&1 | grep -E "error|failed" || true
    NGINX_CONFIG_OK=false
fi

# Check nginx error log for 502 errors
echo ""
echo "Recent nginx errors (last 10 lines):"
sudo tail -10 /var/log/nginx/error.log 2>/dev/null | grep -E "502|upstream|connect" || echo "   No recent 502 errors in log"

echo ""
echo "============================================================"
echo "4. FIXING ISSUES"
echo "============================================================"
echo ""

FIXES_APPLIED=false

# Start Docker services if needed
if [ "$BACKEND_RUNNING" = false ] || [ "$FRONTEND_RUNNING" = false ]; then
    echo "🚀 Starting Docker services..."
    cd "$PROJECT_DIR" || cd ~/automated-trading-platform || exit 1
    
    # Start services with AWS profile
    docker compose --profile aws up -d db backend-aws frontend 2>&1 | head -20 || true
    
    echo "⏳ Waiting for services to start (15 seconds)..."
    sleep 15
    
    FIXES_APPLIED=true
fi

# Restart backend if container is running but not responding
if [ "$BACKEND_RUNNING" = true ] && [ "$BACKEND_ACCESSIBLE" = false ]; then
    echo "🔄 Restarting backend container..."
    docker restart backend-aws || true
    echo "⏳ Waiting for backend to restart (10 seconds)..."
    sleep 10
    FIXES_APPLIED=true
fi

# Restart frontend if container is running but not responding
if [ "$FRONTEND_RUNNING" = true ] && [ "$FRONTEND_ACCESSIBLE" = false ]; then
    echo "🔄 Restarting frontend container..."
    docker restart frontend || true
    echo "⏳ Waiting for frontend to restart (5 seconds)..."
    sleep 5
    FIXES_APPLIED=true
fi

# Reload nginx if it's running
if [ "$NGINX_RUNNING" = true ]; then
    echo "🔄 Reloading nginx configuration..."
    sudo systemctl reload nginx 2>/dev/null || sudo nginx -s reload 2>/dev/null || true
    echo "✅ Nginx reloaded"
    FIXES_APPLIED=true
elif [ "$NGINX_CONFIG_OK" = true ]; then
    echo "🚀 Starting nginx..."
    sudo systemctl start nginx 2>/dev/null || sudo nginx || true
    sleep 2
    FIXES_APPLIED=true
fi

if [ "$FIXES_APPLIED" = true ]; then
    echo ""
    echo "⏳ Waiting for services to stabilize (10 seconds)..."
    sleep 10
fi

echo ""
echo "============================================================"
echo "5. FINAL STATUS CHECK"
echo "============================================================"
echo ""

# Final backend check
echo "Final backend check..."
if curl -s -f --connect-timeout 5 http://localhost:8002/ping_fast > /dev/null 2>&1; then
    BACKEND_FINAL=$(curl -s http://localhost:8002/ping_fast)
    echo "✅ Backend is healthy: $BACKEND_FINAL"
else
    echo "❌ Backend is still not responding"
    echo "   Checking backend logs..."
    docker logs --tail 20 backend-aws 2>&1 | tail -5 || echo "   Cannot access logs"
fi

# Final frontend check
echo ""
echo "Final frontend check..."
if curl -s -f --connect-timeout 5 http://localhost:3000 > /dev/null 2>&1; then
    echo "✅ Frontend is responding"
else
    echo "❌ Frontend is still not responding"
    echo "   Checking frontend logs..."
    docker logs --tail 20 frontend 2>&1 | tail -5 || echo "   Cannot access logs"
fi

# Final nginx check
echo ""
echo "Final nginx check..."
if curl -s -f --connect-timeout 3 http://localhost/api/health > /dev/null 2>&1 || \
   curl -s -f --connect-timeout 3 https://localhost/api/health > /dev/null 2>&1; then
    echo "✅ Nginx can proxy to backend"
else
    echo "⚠️  Nginx proxy test failed (may need more time or SSL setup)"
fi

echo ""
echo "============================================================"
echo "SUMMARY"
echo "============================================================"
echo ""
echo "Backend:  $([ "$BACKEND_ACCESSIBLE" = true ] && echo "✅ OK" || echo "❌ FAILED")"
echo "Frontend: $([ "$FRONTEND_ACCESSIBLE" = true ] && echo "✅ OK" || echo "❌ FAILED")"
echo "Nginx:    $([ "$NGINX_RUNNING" = true ] && echo "✅ OK" || echo "❌ FAILED")"
echo ""
echo "If issues persist:"
echo "  1. Check Docker logs: docker compose --profile aws logs"
echo "  2. Check nginx logs: sudo tail -f /var/log/nginx/error.log"
echo "  3. Verify services: docker compose --profile aws ps"
echo "  4. Check firewall: sudo ufw status"
echo ""
REMOTE_SCRIPT

echo ""
ok "Diagnostic and fix completed!"
echo ""
info "Test the dashboard: https://dashboard.hilovivo.com"
echo ""

