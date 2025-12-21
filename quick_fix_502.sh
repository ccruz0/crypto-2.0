#!/bin/bash

# Quick Fix for 502 Bad Gateway Error
# This script diagnoses and fixes common 502 issues

set -e

SSH_HOST="hilovivo-aws"
REMOTE_PATH="/home/ubuntu/automated-trading-platform"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}=========================================="
echo "🔧 Quick Fix for 502 Bad Gateway"
echo "==========================================${NC}"
echo ""

# Function to run SSH commands
ssh_cmd() {
    ssh -o BatchMode=yes -o ConnectTimeout=10 "$SSH_HOST" "$@" 2>&1
}

# Check SSH connection
echo -e "${CYAN}1. Testing SSH connection...${NC}"
if ! ssh_cmd "echo 'Connected'" > /dev/null 2>&1; then
    echo -e "${RED}❌ Cannot connect to $SSH_HOST${NC}"
    echo "   Please check your SSH configuration"
    exit 1
fi
echo -e "${GREEN}✓ SSH connection OK${NC}"
echo ""

# Check Docker Compose services
echo -e "${CYAN}2. Checking Docker Compose services...${NC}"
SERVICES=$(ssh_cmd "cd $REMOTE_PATH && docker compose --profile aws ps --format json" 2>&1 || echo "[]")

BACKEND_RUNNING=$(echo "$SERVICES" | grep -q '"backend-aws".*"running"' && echo "yes" || echo "no")
FRONTEND_RUNNING=$(echo "$SERVICES" | grep -q '"frontend-aws".*"running"' && echo "yes" || echo "no")

if [ "$BACKEND_RUNNING" = "yes" ]; then
    echo -e "${GREEN}✓ Backend container is running${NC}"
else
    echo -e "${YELLOW}⚠ Backend container is NOT running${NC}"
fi

if [ "$FRONTEND_RUNNING" = "yes" ]; then
    echo -e "${GREEN}✓ Frontend container is running${NC}"
else
    echo -e "${YELLOW}⚠ Frontend container is NOT running${NC}"
fi
echo ""

# Check if ports are listening
echo -e "${CYAN}3. Checking if ports are listening...${NC}"
BACKEND_PORT=$(ssh_cmd "netstat -tln 2>/dev/null | grep ':8002' || ss -tln 2>/dev/null | grep ':8002' || echo ''")
FRONTEND_PORT=$(ssh_cmd "netstat -tln 2>/dev/null | grep ':3000' || ss -tln 2>/dev/null | grep ':3000' || echo ''")

if [ -n "$BACKEND_PORT" ]; then
    echo -e "${GREEN}✓ Port 8002 is listening${NC}"
else
    echo -e "${RED}❌ Port 8002 is NOT listening${NC}"
fi

if [ -n "$FRONTEND_PORT" ]; then
    echo -e "${GREEN}✓ Port 3000 is listening${NC}"
else
    echo -e "${RED}❌ Port 3000 is NOT listening${NC}"
fi
echo ""

# Test backend health
echo -e "${CYAN}4. Testing backend health endpoint...${NC}"
BACKEND_HEALTH=$(ssh_cmd "curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/health 2>/dev/null || echo '000'")
if [ "$BACKEND_HEALTH" = "200" ]; then
    echo -e "${GREEN}✓ Backend health check passed (200)${NC}"
elif [ "$BACKEND_HEALTH" = "000" ]; then
    echo -e "${RED}❌ Backend not responding${NC}"
else
    echo -e "${YELLOW}⚠ Backend returned: $BACKEND_HEALTH${NC}"
fi
echo ""

# Test frontend
echo -e "${CYAN}5. Testing frontend...${NC}"
FRONTEND_TEST=$(ssh_cmd "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null || echo '000'")
if [ "$FRONTEND_TEST" = "200" ]; then
    echo -e "${GREEN}✓ Frontend is responding (200)${NC}"
elif [ "$FRONTEND_TEST" = "000" ]; then
    echo -e "${RED}❌ Frontend not responding${NC}"
else
    echo -e "${YELLOW}⚠ Frontend returned: $FRONTEND_TEST${NC}"
fi
echo ""

# Check nginx status
echo -e "${CYAN}6. Checking nginx status...${NC}"
NGINX_STATUS=$(ssh_cmd "sudo systemctl is-active nginx 2>/dev/null || echo 'inactive'")
if [ "$NGINX_STATUS" = "active" ]; then
    echo -e "${GREEN}✓ Nginx is running${NC}"
else
    echo -e "${RED}❌ Nginx is NOT running${NC}"
fi

NGINX_CONFIG=$(ssh_cmd "sudo nginx -t 2>&1 | grep -q 'successful' && echo 'ok' || echo 'error'")
if [ "$NGINX_CONFIG" = "ok" ]; then
    echo -e "${GREEN}✓ Nginx configuration is valid${NC}"
else
    echo -e "${RED}❌ Nginx configuration has errors${NC}"
    ssh_cmd "sudo nginx -t" || true
fi
echo ""

# Check nginx error logs for 502
echo -e "${CYAN}7. Checking recent nginx errors...${NC}"
RECENT_502=$(ssh_cmd "sudo tail -50 /var/log/nginx/error.log 2>/dev/null | grep -c '502' || echo '0'")
if [ "$RECENT_502" -gt "0" ]; then
    echo -e "${YELLOW}⚠ Found $RECENT_502 recent 502 errors in nginx logs${NC}"
    echo "   Last few 502 errors:"
    ssh_cmd "sudo tail -20 /var/log/nginx/error.log 2>/dev/null | grep '502' | tail -3" || true
else
    echo -e "${GREEN}✓ No recent 502 errors in nginx logs${NC}"
fi
echo ""

# Summary and recommendations
echo -e "${CYAN}=========================================="
echo "📊 Summary"
echo "==========================================${NC}"
echo ""

FIXES_NEEDED=0

if [ "$BACKEND_RUNNING" != "yes" ] || [ -z "$BACKEND_PORT" ] || [ "$BACKEND_HEALTH" != "200" ]; then
    echo -e "${YELLOW}⚠ Backend needs attention${NC}"
    FIXES_NEEDED=$((FIXES_NEEDED + 1))
fi

if [ "$FRONTEND_RUNNING" != "yes" ] || [ -z "$FRONTEND_PORT" ] || [ "$FRONTEND_TEST" != "200" ]; then
    echo -e "${YELLOW}⚠ Frontend needs attention${NC}"
    FIXES_NEEDED=$((FIXES_NEEDED + 1))
fi

if [ "$NGINX_STATUS" != "active" ] || [ "$NGINX_CONFIG" != "ok" ]; then
    echo -e "${YELLOW}⚠ Nginx needs attention${NC}"
    FIXES_NEEDED=$((FIXES_NEEDED + 1))
fi

if [ $FIXES_NEEDED -eq 0 ]; then
    echo -e "${GREEN}✅ All services appear to be running correctly${NC}"
    echo ""
    echo "If you're still seeing 502 errors:"
    echo "  1. Check nginx logs: ssh $SSH_HOST 'sudo tail -100 /var/log/nginx/error.log'"
    echo "  2. Check backend logs: ssh $SSH_HOST 'cd $REMOTE_PATH && docker compose --profile aws logs --tail=100 backend-aws'"
    echo "  3. Try restarting nginx: ssh $SSH_HOST 'sudo systemctl restart nginx'"
else
    echo ""
    echo -e "${CYAN}🔧 Applying fixes...${NC}"
    echo ""
    
    # Fix backend
    if [ "$BACKEND_RUNNING" != "yes" ] || [ -z "$BACKEND_PORT" ]; then
        echo -e "${CYAN}Starting backend...${NC}"
        ssh_cmd "cd $REMOTE_PATH && docker compose --profile aws up -d backend-aws" || echo -e "${RED}Failed to start backend${NC}"
        echo "Waiting 10 seconds for backend to start..."
        sleep 10
    fi
    
    # Fix frontend
    if [ "$FRONTEND_RUNNING" != "yes" ] || [ -z "$FRONTEND_PORT" ]; then
        echo -e "${CYAN}Starting frontend...${NC}"
        ssh_cmd "cd $REMOTE_PATH && docker compose --profile aws up -d frontend-aws" || echo -e "${RED}Failed to start frontend${NC}"
        echo "Waiting 10 seconds for frontend to start..."
        sleep 10
    fi
    
    # Fix nginx
    if [ "$NGINX_STATUS" != "active" ]; then
        echo -e "${CYAN}Starting nginx...${NC}"
        ssh_cmd "sudo systemctl start nginx" || echo -e "${RED}Failed to start nginx${NC}"
    fi
    
    if [ "$NGINX_CONFIG" != "ok" ]; then
        echo -e "${CYAN}Testing nginx configuration...${NC}"
        ssh_cmd "sudo nginx -t" || echo -e "${RED}Nginx config has errors${NC}"
    fi
    
    # Restart nginx to pick up any changes
    echo -e "${CYAN}Restarting nginx...${NC}"
    ssh_cmd "sudo systemctl restart nginx" || echo -e "${RED}Failed to restart nginx${NC}"
    
    echo ""
    echo -e "${GREEN}✅ Fixes applied. Waiting 5 seconds and re-testing...${NC}"
    sleep 5
    
    # Re-test
    echo ""
    echo -e "${CYAN}Re-testing backend...${NC}"
    BACKEND_HEALTH_NEW=$(ssh_cmd "curl -s -o /dev/null -w '%{http_code}' http://localhost:8002/health 2>/dev/null || echo '000'")
    if [ "$BACKEND_HEALTH_NEW" = "200" ]; then
        echo -e "${GREEN}✓ Backend is now healthy${NC}"
    else
        echo -e "${RED}❌ Backend still not responding. Check logs:${NC}"
        echo "   ssh $SSH_HOST 'cd $REMOTE_PATH && docker compose --profile aws logs --tail=50 backend-aws'"
    fi
    
    echo ""
    echo -e "${CYAN}Re-testing frontend...${NC}"
    FRONTEND_TEST_NEW=$(ssh_cmd "curl -s -o /dev/null -w '%{http_code}' http://localhost:3000 2>/dev/null || echo '000'")
    if [ "$FRONTEND_TEST_NEW" = "200" ]; then
        echo -e "${GREEN}✓ Frontend is now responding${NC}"
    else
        echo -e "${RED}❌ Frontend still not responding. Check logs:${NC}"
        echo "   ssh $SSH_HOST 'cd $REMOTE_PATH && docker compose --profile aws logs --tail=50 frontend-aws'"
    fi
fi

echo ""
echo -e "${CYAN}=========================================="
echo "✅ Diagnostic complete"
echo "==========================================${NC}"
echo ""
echo "Next steps:"
echo "  1. Test the dashboard: https://dashboard.hilovivo.com"
echo "  2. Check nginx logs if issues persist:"
echo "     ssh $SSH_HOST 'sudo tail -100 /var/log/nginx/error.log'"
echo "  3. Check backend logs:"
echo "     ssh $SSH_HOST 'cd $REMOTE_PATH && docker compose --profile aws logs --tail=100 backend-aws'"
echo ""

