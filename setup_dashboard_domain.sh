#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Setup Dashboard Domain for Hilo Vivo
# ============================================
# This script configures Nginx and SSL to serve the dashboard
# on your Hilo Vivo website (dashboard.hilovivo.com)
#
# Usage:
#   ./setup_dashboard_domain.sh
#
# Requirements:
#   - Domain DNS pointing to server IP (175.41.189.249)
#   - SSH access to server
#   - Nginx installed on server
#   - Certbot installed for SSL certificates
# ============================================

HOST="${HOST:-ubuntu@175.41.189.249}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/automated-trading-platform}"
# Load unified SSH helper
. ./scripts/ssh_key.sh 2>/dev/null || source ./scripts/ssh_key.sh
DOMAIN="dashboard.hilovivo.com"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if nginx config exists locally
if [ ! -f "nginx/dashboard.conf" ]; then
    error "nginx/dashboard.conf not found"
    exit 1
fi

info "Setting up dashboard domain: $DOMAIN"

# Step 1: Copy nginx config to server
info "Copying Nginx configuration to server..."
scp_cmd nginx/dashboard.conf "$HOST:/tmp/dashboard.conf" || {
    error "Failed to copy nginx config"
    exit 1
}

# Step 2: Setup Nginx on server
info "Configuring Nginx on server..."
ssh_cmd "$HOST" << 'ENDSSH'
    set -euo pipefail
    
    # Install Nginx if not installed
    if ! command -v nginx >/dev/null 2>&1; then
        echo "Installing Nginx..."
        sudo apt-get update
        sudo apt-get install -y nginx
    fi
    
    # Backup existing config if it exists
    if [ -f "/etc/nginx/sites-available/dashboard.conf" ]; then
        sudo cp /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-available/dashboard.conf.backup.$(date +%Y%m%d_%H%M%S)
    fi
    
    # Copy new config
    sudo cp /tmp/dashboard.conf /etc/nginx/sites-available/dashboard.conf
    
    # Create symlink if it doesn't exist
    if [ ! -L "/etc/nginx/sites-enabled/dashboard.conf" ]; then
        sudo ln -s /etc/nginx/sites-available/dashboard.conf /etc/nginx/sites-enabled/dashboard.conf
    fi
    
    # Test Nginx configuration
    sudo nginx -t || {
        echo "Nginx configuration test failed"
        exit 1
    }
    
    # Reload Nginx
    sudo systemctl reload nginx
    
    echo "Nginx configured successfully"
ENDSSH

if [ $? -ne 0 ]; then
    error "Failed to configure Nginx"
    exit 1
fi

# Step 3: Setup SSL certificate
info "Setting up SSL certificate with Let's Encrypt..."
ssh_cmd "$HOST" << ENDSSH
    set -euo pipefail
    
    # Install Certbot if not installed
    if ! command -v certbot >/dev/null 2>&1; then
        echo "Installing Certbot..."
        sudo apt-get update
        sudo apt-get install -y certbot python3-certbot-nginx
    fi
    
    # Obtain SSL certificate
    echo "Obtaining SSL certificate for $DOMAIN..."
    sudo certbot --nginx -d $DOMAIN --non-interactive --agree-tos --email admin@hilovivo.com || {
        echo "Failed to obtain SSL certificate"
        echo "Make sure DNS is pointing to this server:"
        echo "  $DOMAIN -> 175.41.189.249"
        exit 1
    }
    
    # Setup auto-renewal
    sudo systemctl enable certbot.timer
    sudo systemctl start certbot.timer
    
    echo "SSL certificate configured successfully"
ENDSSH

if [ $? -ne 0 ]; then
    warn "SSL certificate setup failed. You may need to:"
    warn "  1. Ensure DNS is pointing $DOMAIN to 175.41.189.249"
    warn "  2. Run manually: ssh $HOST 'sudo certbot --nginx -d $DOMAIN'"
fi

# Step 4: Frontend auto-detects domain (no update needed)
info "Frontend will auto-detect domain - no configuration needed..."
info "The frontend code automatically detects hilovivo.com domains and uses /api for backend calls"

# Step 5: Update backend CORS settings
info "Updating backend CORS configuration..."
ssh_cmd "$HOST" << ENDSSH
    set -euo pipefail
    cd $REMOTE_DIR
    
    # CORS is already configured in backend code for hilovivo.com domains
    # But you can add additional origins via environment variable if needed
    if [ -f ".env.aws" ]; then
        # Add domain to allowed origins (optional - already in code)
        if ! grep -q "CORS_ORIGINS" .env.aws; then
            echo "# Additional CORS origins (comma-separated)" >> .env.aws
            echo "CORS_ORIGINS=https://$DOMAIN,https://www.$DOMAIN" >> .env.aws
            echo "Updated CORS settings in .env.aws"
        fi
    fi
    
    # Restart backend to apply changes
    docker compose --profile aws restart backend-aws
    echo "Backend restarted with new CORS configuration"
ENDSSH

info "Setup completed!"
info ""
info "Dashboard should now be accessible at:"
info "  https://$DOMAIN"
info ""
info "Next steps:"
info "  1. Ensure DNS A record points $DOMAIN to 175.41.189.249"
info "  2. Wait for DNS propagation (can take up to 24 hours)"
info "  3. Test SSL: https://www.ssllabs.com/ssltest/analyze.html?d=$DOMAIN"
info "  4. Access dashboard: https://$DOMAIN"

