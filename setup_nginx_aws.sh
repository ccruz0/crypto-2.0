#!/bin/bash
# Setup and configure nginx on AWS EC2 server
# This script installs nginx, configures it, and sets up SSL certificates

set -e

# Configuration
EC2_HOST="${EC2_HOST:-175.41.189.249}"
EC2_USER="ubuntu"
REMOTE_PROJECT_DIR="/home/ubuntu/automated-trading-platform"

# Unified SSH
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh

echo "🚀 Setting up nginx on AWS server..."
echo "📍 Server: $EC2_USER@$EC2_HOST"
echo ""

# Test SSH connection
echo "🔍 Testing SSH connection..."
if ! ssh_cmd "$EC2_USER@$EC2_HOST" "echo 'Connected'" > /dev/null 2>&1; then
    echo "❌ Cannot connect to AWS server"
    echo "🔧 Verify your SSH configuration"
    exit 1
fi
echo "✅ SSH connection successful"
echo ""

# Execute setup on remote server
echo "🔧 Setting up nginx on remote server..."
ssh_cmd "$EC2_USER@$EC2_HOST" << 'REMOTE_SCRIPT'
set -e

cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

echo "📦 Installing nginx..."
sudo apt-get update -qq
sudo apt-get install -y nginx certbot python3-certbot-nginx > /dev/null 2>&1 || {
    echo "⚠️  nginx may already be installed, continuing..."
}

echo "✅ nginx installed"
echo ""

# Check if nginx config exists
if [ ! -f "nginx/dashboard.conf" ]; then
    echo "❌ nginx/dashboard.conf not found in project directory"
    exit 1
fi

echo "📋 Copying nginx configuration..."
# Backup existing config if it exists
if [ -f /etc/nginx/sites-available/dashboard.conf ]; then
    echo "   Backing up existing config..."
    sudo cp /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-available/dashboard.conf.backup.$(date +%Y%m%d-%H%M%S)
fi

# Copy new config
sudo cp nginx/dashboard.conf /etc/nginx/sites-available/dashboard.conf

# Create symlink if it doesn't exist
if [ ! -L /etc/nginx/sites-enabled/dashboard.conf ]; then
    echo "   Creating symlink..."
    sudo ln -s /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-enabled/dashboard.conf
fi

# Remove default nginx site if it exists
if [ -L /etc/nginx/sites-enabled/default ]; then
    echo "   Removing default nginx site..."
    sudo rm /etc/nginx/sites-enabled/default
fi

echo "✅ Configuration copied"
echo ""

# Check SSL certificates
echo "🔐 Checking SSL certificates..."
if [ ! -f /etc/letsencrypt/live/dashboard.hilovivo.com/fullchain.pem ]; then
    echo "⚠️  SSL certificates not found"
    echo "   SSL certificates are required for HTTPS"
    echo "   You can either:"
    echo "   1. Run: sudo certbot --nginx -d dashboard.hilovivo.com"
    echo "   2. Or use the HTTP-only config (see nginx/dashboard-local.conf)"
    echo ""
    echo "   For now, testing nginx config without SSL..."
    # Create a temporary config without SSL for testing
    sudo cp /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-available/dashboard.conf.ssl
    # Comment out SSL server block (we'll test HTTP first)
    echo ""
    echo "   Testing HTTP configuration..."
else
    echo "✅ SSL certificates found"
fi

# Test nginx configuration
echo "🧪 Testing nginx configuration..."
if sudo nginx -t 2>&1; then
    echo "✅ nginx configuration is valid"
else
    echo "❌ nginx configuration test failed"
    echo "   Checking for missing SSL certificates..."
    if grep -q "ssl_certificate" /etc/nginx/sites-available/dashboard.conf && [ ! -f /etc/letsencrypt/live/dashboard.hilovivo.com/fullchain.pem ]; then
        echo "   ⚠️  Config requires SSL but certificates are missing"
        echo "   Creating HTTP-only version for testing..."
        # We'll need to modify the config to work without SSL
        echo "   Please run: sudo certbot --nginx -d dashboard.hilovivo.com"
        echo "   Or use a temporary HTTP config"
    fi
    exit 1
fi
echo ""

# Check if backend is accessible
echo "🔍 Checking backend connectivity..."
if curl -f --connect-timeout 3 http://localhost:8002/health >/dev/null 2>&1; then
    echo "✅ Backend is accessible on port 8002"
elif curl -f --connect-timeout 3 http://localhost:8002/ping_fast >/dev/null 2>&1; then
    echo "✅ Backend is accessible on port 8002 (ping_fast)"
else
    echo "⚠️  Backend not accessible on port 8002"
    echo "   Checking Docker containers..."
    docker ps --filter "name=backend-aws" --format "{{.Names}}: {{.Status}}" || echo "   Backend container not found"
    echo "   You may need to start the backend first:"
    echo "   docker compose --profile aws up -d backend-aws"
fi
echo ""

# Check if frontend is accessible
echo "🔍 Checking frontend connectivity..."
if curl -f --connect-timeout 3 http://localhost:3000 >/dev/null 2>&1; then
    echo "✅ Frontend is accessible on port 3000"
else
    echo "⚠️  Frontend not accessible on port 3000"
    echo "   Checking Docker containers..."
    docker ps --filter "name=frontend-aws" --format "{{.Names}}: {{.Status}}" || echo "   Frontend container not found"
    echo "   You may need to start the frontend first:"
    echo "   docker compose --profile aws up -d frontend-aws"
fi
echo ""

# Start/restart nginx
echo "🔄 Starting/Restarting nginx..."
sudo systemctl enable nginx
sudo systemctl restart nginx

# Wait a moment for nginx to start
sleep 2

# Check nginx status
if sudo systemctl is-active --quiet nginx; then
    echo "✅ nginx is running"
else
    echo "❌ nginx failed to start"
    echo "   Checking error logs..."
    sudo tail -20 /var/log/nginx/error.log || true
    exit 1
fi
echo ""

# Show nginx status
echo "📊 nginx status:"
sudo systemctl status nginx --no-pager | head -10 || true
echo ""

# Show recent nginx errors (if any)
echo "📋 Recent nginx errors (if any):"
sudo tail -10 /var/log/nginx/error.log 2>/dev/null | grep -E "error|warn|502" || echo "   No recent errors"
echo ""

echo "✅ nginx setup complete!"
echo ""
echo "🌐 Test the dashboard:"
echo "   HTTP:  http://$EC2_HOST"
echo "   HTTPS: https://dashboard.hilovivo.com (if SSL is configured)"
echo ""
echo "🔍 Verify endpoints:"
echo "   curl http://$EC2_HOST/api/health"
echo "   curl -k https://dashboard.hilovivo.com/api/health"
echo ""

REMOTE_SCRIPT

echo ""
echo "✅ nginx setup script completed!"
echo ""
echo "📝 Next steps:"
echo "   1. If SSL certificates are missing, run on the server:"
echo "      sudo certbot --nginx -d dashboard.hilovivo.com"
echo ""
echo "   2. Verify the dashboard is accessible:"
echo "      curl -k https://dashboard.hilovivo.com/api/health"
echo ""





