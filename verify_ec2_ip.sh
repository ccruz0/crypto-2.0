#!/bin/bash
# Script to verify outbound IP from EC2 host and backend container
# Run this on EC2 instance via AWS SSM Session Manager

set -e

echo "========================================="
echo "EC2 Outbound IP Verification"
echo "========================================="
echo ""

echo "1. EC2 Host Outbound IP:"
HOST_IP=$(curl -s https://api.ipify.org)
echo "   Host IP: $HOST_IP"
echo ""

echo "2. Backend Container Outbound IP:"
cd ~/automated-trading-platform || cd /home/ubuntu/automated-trading-platform

# Try python3 first, fallback to python
CONTAINER_IP=$(docker compose --profile aws exec -T backend-aws python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())" 2>/dev/null || \
  docker compose --profile aws exec -T backend-aws python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())" 2>/dev/null || \
  echo "ERROR: Could not get container IP")

echo "   Container IP: $CONTAINER_IP"
echo ""

echo "3. Comparison:"
if [ "$HOST_IP" = "$CONTAINER_IP" ]; then
    echo "   ✅ Host IP == Container IP (MATCH)"
    echo "   ✅ Backend uses EC2's public IP for outbound"
else
    echo "   ⚠️  Host IP != Container IP (MISMATCH)"
    echo "   ⚠️  Backend may be routing through VPN/proxy"
fi
echo ""

echo "4. Backend Health Check (localhost):"
curl -m 5 -v http://localhost:8002/api/health 2>&1 | head -30
echo ""

echo "5. Container Status:"
docker compose --profile aws ps
echo ""

echo "========================================="
echo "Summary:"
echo "========================================="
echo "Host Outbound IP: $HOST_IP"
echo "Container Outbound IP: $CONTAINER_IP"
echo "Crypto.com whitelist should use: $HOST_IP"


