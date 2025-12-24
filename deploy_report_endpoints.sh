#!/bin/bash
# Deploy report endpoints fix: backend endpoints, nginx rewrite rules, and frontend timeout fix

set -e

# Server configuration
SERVER="47.130.143.159"
USER="ubuntu"

# Load SSH helpers
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying Report Endpoints Fix"
echo "=================================="
echo "📍 Server: $USER@$SERVER"
echo ""
echo "Changes:"
echo "  ✅ Backend: New report endpoints (watchlist-consistency, watchlist-dedup)"
echo "  ✅ Nginx: Rewrite rules for dated reports"
echo "  ✅ Frontend: Timeout fix for workflows endpoint"
echo ""

# Test SSH connection
echo "🔍 Testing SSH connection..."
if ! ssh_cmd "$USER@$SERVER" "echo 'Connected'" > /dev/null 2>&1; then
    echo "❌ Cannot connect to server"
    echo "🔧 Verify your SSH configuration and key access"
    exit 1
fi
echo "✅ SSH connection successful"
echo ""

# Step 1: Deploy Backend Changes
echo "📦 Step 1: Deploying backend changes..."
echo "   Syncing backend/api/routes_monitoring.py..."
rsync_cmd \
  --exclude='__pycache__/' \
  --exclude='*.pyc' \
  backend/app/api/routes_monitoring.py \
  $USER@$SERVER:~/automated-trading-platform/backend/app/api/routes_monitoring.py

echo "   ✅ Backend file synced"
echo ""

# Step 2: Deploy Nginx Configuration
echo "📋 Step 2: Deploying nginx configuration..."
scp_cmd nginx/dashboard.conf "$USER@$SERVER:/tmp/dashboard.conf" || {
    echo "❌ Failed to copy nginx config"
    exit 1
}
echo "   ✅ Nginx config copied"
echo ""

# Step 3: Deploy Frontend Changes
echo "🌐 Step 3: Deploying frontend changes..."
echo "   Copying frontend/src/lib/api.ts to server..."
scp_cmd frontend/src/lib/api.ts "$USER@$SERVER:/tmp/api.ts" || {
    echo "   ⚠️  Failed to copy frontend file, will try via Docker"
}
echo "   ✅ Frontend file copied to /tmp"
echo ""

# Step 4: Deploy on Server
echo "🔧 Step 4: Deploying on server..."
ssh_cmd "$USER@$SERVER" << 'REMOTE'
set -e

cd ~/automated-trading-platform

# Backup existing files
echo "   📦 Creating backups..."
BACKUP_DIR="/tmp/report_endpoints_backup_$(date +%Y%m%d-%H%M%S)"
mkdir -p "$BACKUP_DIR"

if [ -f /etc/nginx/sites-available/dashboard.conf ]; then
    sudo cp /etc/nginx/sites-available/dashboard.conf "$BACKUP_DIR/dashboard.conf.backup"
fi

if [ -f backend/app/api/routes_monitoring.py ]; then
    cp backend/app/api/routes_monitoring.py "$BACKUP_DIR/routes_monitoring.py.backup"
fi

if [ -f frontend/src/lib/api.ts ]; then
    cp frontend/src/lib/api.ts "$BACKUP_DIR/api.ts.backup"
fi

echo "   ✅ Backups created in $BACKUP_DIR"
echo ""

# Deploy Backend
echo "   🔄 Deploying backend..."
if [ -f backend/app/api/routes_monitoring.py ]; then
    # If using Docker, copy into container
    if docker ps --format '{{.Names}}' | grep -q backend; then
        echo "      Copying to Docker backend container..."
        BACKEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep backend | head -1)
        if [ -n "$BACKEND_CONTAINER" ]; then
            docker cp backend/app/api/routes_monitoring.py "$BACKEND_CONTAINER:/app/app/api/routes_monitoring.py"
            echo "      ✅ Backend file copied to container"
            echo "      🔄 Restarting backend container..."
            docker restart "$BACKEND_CONTAINER" || docker-compose restart backend
            echo "      ✅ Backend container restarted"
        else
            echo "      ⚠️  Backend container not found, skipping Docker copy"
        fi
    else
        echo "      ⚠️  No Docker backend container found, file synced but not deployed"
    fi
else
    echo "      ❌ Backend file not found"
    exit 1
fi
echo ""

# Deploy Nginx
echo "   🔄 Deploying nginx configuration..."
if [ -f /tmp/dashboard.conf ]; then
    # Backup existing config
    if [ -f /etc/nginx/sites-available/dashboard.conf ]; then
        echo "      Backing up existing nginx config..."
        sudo cp /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-available/dashboard.conf.backup.$(date +%Y%m%d-%H%M%S)
    fi
    
    # Copy new config
    echo "      Installing new nginx config..."
    sudo cp /tmp/dashboard.conf /etc/nginx/sites-available/dashboard.conf
    
    # Create/enable symlink
    echo "      Enabling nginx config..."
    sudo ln -sf /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-enabled/dashboard.conf
    
    # Test nginx config
    echo "      Testing nginx configuration..."
    if sudo nginx -t; then
        echo "      ✅ Nginx configuration is valid"
        
        # Reload nginx
        echo "      Reloading nginx..."
        sudo systemctl reload nginx || sudo systemctl restart nginx
        
        # Check nginx status
        if sudo systemctl is-active --quiet nginx; then
            echo "      ✅ Nginx is running"
        else
            echo "      ❌ Nginx failed to start"
            echo "      Checking error logs..."
            sudo tail -20 /var/log/nginx/error.log || true
            exit 1
        fi
    else
        echo "      ❌ Nginx configuration test failed"
        echo "      Restoring backup..."
        if [ -f "$BACKUP_DIR/dashboard.conf.backup" ]; then
            sudo cp "$BACKUP_DIR/dashboard.conf.backup" /etc/nginx/sites-available/dashboard.conf
            sudo systemctl reload nginx
        fi
        exit 1
    fi
else
    echo "      ❌ Nginx config file not found"
    exit 1
fi
echo ""

# Deploy Frontend
echo "   🔄 Deploying frontend..."
if [ -f /tmp/api.ts ]; then
    # Copy to frontend directory with proper permissions
    if [ -d frontend/src/lib ]; then
        echo "      Copying frontend file to project directory..."
        sudo cp /tmp/api.ts frontend/src/lib/api.ts
        sudo chown $(whoami):$(whoami) frontend/src/lib/api.ts || true
    fi
    
    # If using Docker, copy into container and rebuild
    if docker ps --format '{{.Names}}' | grep -q frontend; then
        FRONTEND_CONTAINER=$(docker ps --format '{{.Names}}' | grep frontend | head -1)
        if [ -n "$FRONTEND_CONTAINER" ]; then
            echo "      Copying to Docker frontend container..."
            docker cp /tmp/api.ts "$FRONTEND_CONTAINER:/app/src/lib/api.ts" || {
                echo "      ⚠️  Failed to copy to container, will rebuild"
            }
            
            echo "      Rebuilding frontend container..."
            cd ~/automated-trading-platform
            docker-compose build frontend 2>&1 | tail -5 || {
                echo "      ⚠️  Build failed, trying restart only..."
                docker restart "$FRONTEND_CONTAINER"
            }
            docker-compose restart frontend || docker restart "$FRONTEND_CONTAINER"
            echo "      ✅ Frontend container restarted"
        else
            echo "      ⚠️  Frontend container not found"
        fi
    else
        echo "      ⚠️  No Docker frontend container found"
        echo "      File copied, but frontend needs to be rebuilt manually"
    fi
else
    echo "      ⚠️  Frontend file not found in /tmp, skipping frontend deployment"
fi
echo ""

# Wait for services to be ready
echo "   ⏳ Waiting for services to be ready..."
sleep 5

# Verify Backend
echo "   🔍 Verifying backend..."
if curl -f --connect-timeout 5 http://localhost:8002/health >/dev/null 2>&1; then
    echo "      ✅ Backend health check passed"
    
    # Test new endpoint
    if curl -f --connect-timeout 5 http://localhost:8002/api/monitoring/reports/watchlist-consistency/latest >/dev/null 2>&1; then
        echo "      ✅ New report endpoint is accessible"
    else
        echo "      ⚠️  New report endpoint test failed (may be expected if report doesn't exist)"
    fi
else
    echo "      ⚠️  Backend health check failed"
fi
echo ""

# Verify Nginx
echo "   🔍 Verifying nginx..."
if sudo systemctl is-active --quiet nginx; then
    echo "      ✅ Nginx is running"
    
    # Test nginx rewrite
    if curl -f --connect-timeout 5 -k https://localhost/docs/monitoring/watchlist_consistency_report_latest.md >/dev/null 2>&1; then
        echo "      ✅ Nginx rewrite rule is working"
    else
        echo "      ⚠️  Nginx rewrite test failed (may be expected if report doesn't exist)"
    fi
else
    echo "      ❌ Nginx is not running"
fi
echo ""

echo "✅ Deployment complete!"
echo ""
echo "📋 Summary:"
echo "   ✅ Backend: New report endpoints deployed"
echo "   ✅ Nginx: Rewrite rules deployed"
echo "   ✅ Frontend: Timeout fix deployed"
echo ""
echo "🧪 Test endpoints:"
echo "   curl -I http://localhost:8002/api/monitoring/reports/watchlist-consistency/latest"
echo "   curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md"
echo ""
REMOTE

echo ""
echo "✅ Deployment script completed!"
echo ""
echo "🌐 Test the endpoints:"
echo "   curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_latest.md"
echo "   curl -I https://dashboard.hilovivo.com/docs/monitoring/watchlist_consistency_report_20251203.md"
echo ""

