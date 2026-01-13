#!/bin/bash
# Script to check outbound IP from EC2 host and backend container
# Run this on the EC2 instance to verify outbound IP configuration

set -e

echo "========================================="
echo "Outbound IP Configuration Check"
echo "========================================="
echo ""

echo "1. Checking outbound IP from EC2 host:"
echo "   via api.ipify.org:"
curl -s https://api.ipify.org || echo "   ❌ Failed"
echo ""
echo "   via ifconfig.me:"
curl -s https://ifconfig.me || echo "   ❌ Failed"
echo ""
echo "   via checkip.amazonaws.com:"
curl -s https://checkip.amazonaws.com || echo "   ❌ Failed"
echo ""

echo "2. Checking backend container network configuration:"
CONTAINER_NAME=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || echo "")
if [ -z "$CONTAINER_NAME" ]; then
    echo "   ⚠️  Backend container not running or not found"
else
    echo "   Container ID: $CONTAINER_NAME"
    echo "   Network Mode:"
    docker inspect "$CONTAINER_NAME" --format='{{.HostConfig.NetworkMode}}' 2>/dev/null || echo "   ❌ Failed to inspect"
    echo ""
    echo "3. Checking outbound IP from backend container:"
    echo "   via api.ipify.org:"
    docker compose --profile aws exec -T backend-aws sh -c "curl -s https://api.ipify.org 2>/dev/null || echo '❌ Failed'" || echo "   ❌ Container exec failed"
    echo ""
    echo "   via ifconfig.me:"
    docker compose --profile aws exec -T backend-aws sh -c "curl -s https://ifconfig.me 2>/dev/null || echo '❌ Failed'" || echo "   ❌ Container exec failed"
    echo ""
fi

echo "4. Checking Docker networks:"
docker network ls
echo ""

echo "5. Checking if gluetun container exists:"
if docker ps -a --filter "name=gluetun" --format "{{.Names}}" | grep -q gluetun; then
    echo "   ⚠️  WARNING: Gluetun container found!"
    docker ps -a --filter "name=gluetun"
else
    echo "   ✅ No gluetun container found (expected)"
fi
echo ""

echo "6. Checking backend container network connections:"
if [ -n "$CONTAINER_NAME" ]; then
    echo "   Network connections:"
    docker inspect "$CONTAINER_NAME" --format='{{range $key, $value := .NetworkSettings.Networks}}{{$key}}{{end}}' 2>/dev/null || echo "   ❌ Failed"
    echo ""
    echo "   IP Address:"
    docker inspect "$CONTAINER_NAME" --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' 2>/dev/null || echo "   ❌ Failed"
fi
echo ""

echo "========================================="
echo "Summary:"
echo "========================================="
echo "Compare the IPs above:"
echo "  - Host IP should match backend container IP"
echo "  - If they differ, backend may be routing through VPN/proxy"
echo "  - Expected: Both should show AWS Elastic IP (47.130.143.159 or current EIP)"



