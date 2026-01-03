#!/bin/bash
# Script to verify outbound IP and health from EC2 instance
# Run this INSIDE EC2 via AWS SSM Session Manager ONLY
# This script is READ-ONLY: it does not make any changes

set -euo pipefail

echo "========================================="
echo "EC2 Outbound IP & Health Verification"
echo "========================================="
echo ""

echo "1. System Information:"
echo "   Hostname: $(hostname)"
echo "   OS: $(uname -a)"
echo "   User: $(whoami)"
echo ""

echo "2. EC2 Host Outbound IP:"
HOST_IP=$(python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode().strip())" 2>/dev/null || \
  python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode().strip())" 2>/dev/null || \
  echo "ERROR: Could not determine host IP")
echo "   EC2 Host Outbound IP: $HOST_IP"
echo ""

echo "3. Backend Container Outbound IP:"
cd ~/automated-trading-platform 2>/dev/null || cd /home/ubuntu/automated-trading-platform 2>/dev/null || {
    echo "   ❌ ERROR: Cannot find project directory"
    exit 1
}

CONTAINER_IP=$(docker compose --profile aws exec -T backend-aws python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode().strip())" 2>/dev/null || \
  docker compose --profile aws exec -T backend-aws python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org', timeout=10).read().decode().strip())" 2>/dev/null || \
  echo "ERROR: Could not determine container IP")

echo "   Backend Container Outbound IP: $CONTAINER_IP"
echo ""

echo "4. IP Comparison:"
if [ "$HOST_IP" = "$CONTAINER_IP" ] && [ "$HOST_IP" != "ERROR" ]; then
    echo "   ✅ Host IP == Container IP (MATCH)"
    echo "   ✅ Backend uses EC2'''s public IP for outbound traffic"
    echo "   ✅ Crypto.com whitelist should use: $HOST_IP"
elif [ "$HOST_IP" = "ERROR" ] || [ "$CONTAINER_IP" = "ERROR" ]; then
    echo "   ⚠️  Could not compare IPs (error getting one or both)"
else
    echo "   ⚠️  Host IP != Container IP (MISMATCH)"
    echo "   ⚠️  Backend may be routing through VPN/proxy"
    echo "   ⚠️  Investigate network configuration"
fi
echo ""

echo "5. Backend Health Check (localhost):"
echo "   Attempting: http://localhost:8002/api/health"
echo ""

# Try curl first, fallback to python urllib
LOCAL_HEALTH=$(curl -m 5 -s -w "\nHTTP_STATUS:%{http_code}" http://localhost:8002/api/health 2>/dev/null || \
  python3 -c "
import urllib.request
import sys
try:
    resp = urllib.request.urlopen('http://localhost:8002/api/health', timeout=5)
    print(resp.read().decode('utf-8'))
    print(f'\nHTTP_STATUS:{resp.getcode()}')
except Exception as e:
    print(f'ERROR: {e}', file=sys.stderr)
    sys.exit(1)
" 2>&1 || echo "ERROR")

HTTP_STATUS=$(echo "$LOCAL_HEALTH" | grep "HTTP_STATUS:" | cut -d: -f2 || echo "ERROR")
if [ "$HTTP_STATUS" = "200" ]; then
    echo "   ✅ Backend is healthy (HTTP 200)"
    echo "   Response:"
    echo "$LOCAL_HEALTH" | grep -v "HTTP_STATUS:" | head -20
else
    echo "   ❌ Backend health check failed (HTTP Status: $HTTP_STATUS)"
    echo "   Output:"
    echo "$LOCAL_HEALTH" | head -20
fi
echo ""

echo "6. Container Status:"
echo "   Running: docker compose --profile aws ps"
echo ""
docker compose --profile aws ps 2>/dev/null || echo "   ⚠️  Could not get container status"
echo ""

echo "7. EC2 Public IP (for external access):"
if command -v curl >/dev/null 2>&1; then
    EC2_PUBLIC_IP=$(curl -s --max-time 2 http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || \
      echo "ERROR: Could not get from metadata")
else
    EC2_PUBLIC_IP=$(python3 -c "import urllib.request; print(urllib.request.urlopen('http://169.254.169.254/latest/meta-data/public-ipv4', timeout=2).read().decode().strip())" 2>/dev/null || \
      echo "ERROR: Could not get from metadata")
fi
echo "   EC2 Public IP: $EC2_PUBLIC_IP"
echo ""

echo "========================================="
echo "Summary:"
echo "========================================="
echo "✅ EC2 Host Outbound IP: $HOST_IP"
echo "✅ Backend Container Outbound IP: $CONTAINER_IP"
echo "✅ Crypto.com Whitelist IP: $HOST_IP (use this for IP whitelisting)"
echo "✅ Backend Health: $([ "$HTTP_STATUS" = "200" ] && echo "HEALTHY" || echo "UNHEALTHY")"
echo "✅ EC2 Public IP: $EC2_PUBLIC_IP"
echo ""
echo "Next Steps:"
echo "  1. Verify Crypto.com whitelist includes: $HOST_IP"
echo "  2. Add Security Group inbound rules to allow external access (see AWS_SSM_RUNBOOK.md)"
echo "  3. Test external access from your Mac using scripts/verify_inbound_access_from_mac.sh"
