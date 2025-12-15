#!/usr/bin/env bash
set -euo pipefail

# ============================================
# Update DNS for dashboard.hilovivo.com
# ============================================
# This script helps update the DNS A record
# for dashboard.hilovivo.com to point to the
# current server IP.
#
# Usage:
#   ./scripts/update_dashboard_dns.sh
# ============================================

DOMAIN="dashboard.hilovivo.com"
NEW_IP="47.130.143.159"
OLD_IP="175.41.189.249"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
BLUE='\033[0;34m'
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

header() {
    echo -e "${BLUE}==========================================${NC}"
    echo -e "${BLUE}$1${NC}"
    echo -e "${BLUE}==========================================${NC}"
}

# Check current DNS
header "Current DNS Status"
CURRENT_IP=$(dig +short "$DOMAIN" A | head -1)
if [ -z "$CURRENT_IP" ]; then
    error "Could not resolve $DOMAIN"
    exit 1
fi

echo "Domain: $DOMAIN"
echo "Current IP: $CURRENT_IP"
echo "Required IP: $NEW_IP"
echo ""

if [ "$CURRENT_IP" = "$NEW_IP" ]; then
    info "DNS is already pointing to the correct IP ($NEW_IP)"
    info "No update needed!"
    exit 0
fi

if [ "$CURRENT_IP" != "$OLD_IP" ]; then
    warn "Current IP ($CURRENT_IP) is neither old ($OLD_IP) nor new ($NEW_IP)"
    warn "Proceeding with update anyway..."
fi

# Check nameservers
header "DNS Provider Detection"
NAMESERVERS=$(dig NS hilovivo.com +short | tr '\n' ' ')
echo "Nameservers: $NAMESERVERS"
echo ""

# Detect provider
PROVIDER=""
if echo "$NAMESERVERS" | grep -qi "cloudflare"; then
    PROVIDER="cloudflare"
    info "Detected: Cloudflare"
elif echo "$NAMESERVERS" | grep -qi "awsdns\|route53"; then
    PROVIDER="route53"
    info "Detected: AWS Route53"
elif echo "$NAMESERVERS" | grep -qi "dns-parking"; then
    PROVIDER="parking"
    info "Detected: DNS Parking Service"
else
    PROVIDER="unknown"
    warn "Could not detect DNS provider"
fi

echo ""

# Provider-specific instructions
header "DNS Update Instructions"

case "$PROVIDER" in
    cloudflare)
        info "To update DNS via Cloudflare:"
        echo ""
        echo "1. Log in to: https://dash.cloudflare.com"
        echo "2. Select domain: hilovivo.com"
        echo "3. Go to: DNS → Records"
        echo "4. Find A record for: dashboard"
        echo "5. Edit → Change IP to: $NEW_IP"
        echo "6. Set TTL to: Auto (or 300)"
        echo "7. Save"
        echo ""
        echo "Or use Cloudflare API:"
        echo "  export CF_API_TOKEN='your-api-token'"
        echo "  export CF_ZONE_ID='your-zone-id'"
        echo "  ./scripts/update_dashboard_dns_cloudflare.sh"
        ;;
    route53)
        info "To update DNS via AWS Route53:"
        echo ""
        echo "1. AWS Console → Route53 → Hosted zones"
        echo "2. Select: hilovivo.com"
        echo "3. Find A record: dashboard.hilovivo.com"
        echo "4. Edit → Change value to: $NEW_IP"
        echo "5. Set TTL to: 300"
        echo "6. Save changes"
        echo ""
        echo "Or use AWS CLI:"
        echo "  aws route53 change-resource-record-sets \\"
        echo "    --hosted-zone-id YOUR_ZONE_ID \\"
        echo "    --change-batch file://dns-update.json"
        ;;
    parking)
        info "DNS is managed by a parking service"
        echo ""
        echo "You need to:"
        echo "1. Log in to your domain registrar"
        echo "2. Find DNS management settings"
        echo "3. Update A record for 'dashboard' to: $NEW_IP"
        echo ""
        echo "Common registrars:"
        echo "  - GoDaddy: https://dcc.godaddy.com"
        echo "  - Namecheap: https://www.namecheap.com/myaccount/login"
        echo "  - Google Domains: https://domains.google.com"
        echo ""
        warn "If you're using a DNS parking service, you may need to:"
        warn "  - Change nameservers to a proper DNS provider (Cloudflare, Route53)"
        warn "  - Or access your registrar's DNS management panel"
        ;;
    *)
        info "Manual DNS Update Required"
        echo ""
        echo "Update the A record for $DOMAIN:"
        echo "  Type: A"
        echo "  Name: dashboard (or dashboard.hilovivo.com)"
        echo "  Value: $NEW_IP"
        echo "  TTL: 300 (5 minutes)"
        echo ""
        echo "Access your DNS provider and make this change."
        ;;
esac

echo ""
header "After DNS Update"

echo "1. Wait 5-60 minutes for DNS propagation"
echo "2. Verify DNS:"
echo "   dig +short $DOMAIN A"
echo "   # Should return: $NEW_IP"
echo ""
echo "3. Run verification script:"
echo "   ./scripts/verify_dashboard_dns.sh"
echo ""
echo "4. Test in browser:"
echo "   https://$DOMAIN"

echo ""
info "DNS update instructions displayed above."
info "Please update DNS manually using your DNS provider's interface."

