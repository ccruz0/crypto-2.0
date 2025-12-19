#!/bin/bash
# Deploy nginx configuration to fix 502 error on dashboard.hilovivo.com

set -e

# Server configuration
SERVER="47.130.143.159"
USER="ubuntu"
CONFIG_FILE="nginx/dashboard.conf"

# Load SSH helpers
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Deploying nginx config to fix 502 error"
echo "📍 Server: $USER@$SERVER"
echo "📄 Config: $CONFIG_FILE"
echo ""

# Check if config file exists
if [ ! -f "$CONFIG_FILE" ]; then
    echo "❌ Config file not found: $CONFIG_FILE"
    exit 1
fi

# Test SSH connection
echo "🔍 Testing SSH connection..."
if ! ssh_cmd "$USER@$SERVER" "echo 'Connected'" > /dev/null 2>&1; then
    echo "❌ Cannot connect to server"
    echo "🔧 Verify your SSH configuration and key access"
    exit 1
fi
echo "✅ SSH connection successful"
echo ""

# Copy config to server
echo "📋 Copying config to server..."
scp_cmd "$CONFIG_FILE" "$USER@$SERVER:/tmp/dashboard.conf" || {
    echo "❌ Failed to copy config"
    exit 1
}
echo "✅ Config copied"
echo ""

# Deploy on server
echo "🔧 Deploying on server..."
ssh_cmd "$USER@$SERVER" << 'REMOTE'
set -e

# Backup existing config
if [ -f /etc/nginx/sites-available/dashboard.conf ]; then
    echo "   Backing up existing config..."
    sudo cp /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-available/dashboard.conf.backup.$(date +%Y%m%d-%H%M%S)
fi

# Copy new config
echo "   Installing new config..."
sudo cp /tmp/dashboard.conf /etc/nginx/sites-available/dashboard.conf

# Create/enable symlink
echo "   Enabling config..."
sudo ln -sf /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-enabled/dashboard.conf

# Test nginx config
echo "   Testing nginx configuration..."
if sudo nginx -t; then
    echo "   ✅ Nginx configuration is valid"
else
    echo "   ❌ Nginx configuration test failed"
    exit 1
fi

# Reload nginx
echo "   Reloading nginx..."
sudo systemctl reload nginx || sudo systemctl restart nginx

# Check nginx status
if sudo systemctl is-active --quiet nginx; then
    echo "   ✅ Nginx is running"
else
    echo "   ❌ Nginx failed to start"
    echo "   Checking error logs..."
    sudo tail -20 /var/log/nginx/error.log || true
    exit 1
fi

# Check backend connectivity
echo ""
echo "   🔍 Checking backend connectivity..."
if curl -f --connect-timeout 3 http://localhost:8002/health >/dev/null 2>&1; then
    echo "   ✅ Backend is accessible on port 8002"
elif curl -f --connect-timeout 3 http://localhost:8002/ping_fast >/dev/null 2>&1; then
    echo "   ✅ Backend is accessible on port 8002 (ping_fast)"
else
    echo "   ⚠️  Backend not accessible on port 8002"
    echo "   Checking Docker containers..."
    docker ps --filter "name=backend" --format "{{.Names}}: {{.Status}}" || echo "   Backend container not found"
fi

# Check frontend connectivity
echo "   🔍 Checking frontend connectivity..."
if curl -f --connect-timeout 3 http://localhost:3000 >/dev/null 2>&1; then
    echo "   ✅ Frontend is accessible on port 3000"
else
    echo "   ⚠️  Frontend not accessible on port 3000"
    echo "   Checking Docker containers..."
    docker ps --filter "name=frontend" --format "{{.Names}}: {{.Status}}" || echo "   Frontend container not found"
fi

echo ""
echo "✅ Deployment complete!"
REMOTE

echo ""
echo "✅ Nginx configuration deployed!"
echo ""
echo "🌐 Test the dashboard:"
echo "   curl -k https://dashboard.hilovivo.com/api/health"
echo "   curl -k https://dashboard.hilovivo.com/"
echo ""
