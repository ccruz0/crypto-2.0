#!/bin/bash
# Script to verify inbound access to EC2 from Mac
# Run this on your Mac to test external access to EC2 backend/frontend
# This script is READ-ONLY: it does not make any changes
# Usage: ./scripts/verify_inbound_access_from_mac.sh <EC2_PUBLIC_IP> [YOUR_PUBLIC_IP]

set -euo pipefail

EC2_IP="${1:-}"
MY_IP_PROVIDED="${2:-}"

if [ -z "$EC2_IP" ]; then
    echo "Usage: $0 <EC2_PUBLIC_IP> [YOUR_PUBLIC_IP]"
    echo "Example: $0 54.254.150.31"
    exit 1
fi

echo "========================================="
echo "Inbound Access Verification (from Mac)"
echo "========================================="
echo ""

echo "1. Mac Public IP:"
MY_IP=$(curl -s https://api.ipify.org 2>/dev/null || \
  python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())" 2>/dev/null || \
  python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())" 2>/dev/null || \
  echo "ERROR: Could not determine public IP")
echo "   Mac Public IP: $MY_IP"
if [ -n "$MY_IP_PROVIDED" ] && [ "$MY_IP" != "$MY_IP_PROVIDED" ]; then
    echo "   ⚠️  WARNING: Provided IP ($MY_IP_PROVIDED) differs from detected IP ($MY_IP)"
    echo "   ⚠️  Security Group should allow: $MY_IP/32"
fi
echo ""

echo "2. Testing Backend Health Endpoint:"
echo "   URL: http://$EC2_IP:8002/api/health"
echo "   Running: curl -m 5 -v http://$EC2_IP:8002/api/health"
echo ""
BACKEND_RESULT=$(curl -m 5 -s -w "\nHTTP_STATUS:%{http_code}" http://$EC2_IP:8002/api/health 2>&1 || echo "ERROR")
BACKEND_HTTP_STATUS=$(echo "$BACKEND_RESULT" | grep "HTTP_STATUS:" | cut -d: -f2 || echo "ERROR")

if [ "$BACKEND_HTTP_STATUS" = "200" ]; then
    echo "   ✅ Backend health check SUCCESS (HTTP 200)"
    echo "   Response:"
    echo "$BACKEND_RESULT" | grep -v "HTTP_STATUS:" | head -20
elif echo "$BACKEND_RESULT" | grep -q "timeout\|timed out\|Connection refused\|Connection reset"; then
    echo "   ❌ Backend health check FAILED"
    echo "   ⚠️  Likely Security Group inbound blocked"
    echo "   ⚠️  Ensure Security Group allows $MY_IP/32 on port 8002"
    echo "   Error output:"
    echo "$BACKEND_RESULT" | head -10
else
    echo "   ❌ Backend health check FAILED (HTTP $BACKEND_HTTP_STATUS)"
    echo "   Output:"
    echo "$BACKEND_RESULT" | head -20
fi
echo ""

echo "3. Testing Frontend (optional):"
echo "   URL: http://$EC2_IP:3000/"
echo "   Running: curl -m 5 -v http://$EC2_IP:3000/"
echo ""
FRONTEND_RESULT=$(curl -m 5 -s -w "\nHTTP_STATUS:%{http_code}" http://$EC2_IP:3000/ 2>&1 || echo "ERROR")
FRONTEND_HTTP_STATUS=$(echo "$FRONTEND_RESULT" | grep "HTTP_STATUS:" | cut -d: -f2 || echo "ERROR")

if [ "$FRONTEND_HTTP_STATUS" = "200" ]; then
    echo "   ✅ Frontend access SUCCESS (HTTP 200)"
elif echo "$FRONTEND_RESULT" | grep -q "timeout\|timed out\|Connection refused\|Connection reset"; then
    echo "   ❌ Frontend access FAILED"
    echo "   ⚠️  Likely Security Group inbound blocked"
    echo "   ⚠️  Ensure Security Group allows $MY_IP/32 on port 3000 (optional)"
    echo "   Error output:"
    echo "$FRONTEND_RESULT" | head -10
else
    echo "   ⚠️  Frontend access returned HTTP $FRONTEND_HTTP_STATUS"
    echo "   (This is optional - backend is the critical service)"
fi
echo ""

echo "========================================="
echo "Summary:"
echo "========================================="
echo "✅ Mac Public IP: $MY_IP"
echo "✅ Backend Status: $([ "$BACKEND_HTTP_STATUS" = "200" ] && echo "ACCESSIBLE" || echo "BLOCKED/TIMEOUT")"
echo "✅ Frontend Status: $([ "$FRONTEND_HTTP_STATUS" = "200" ] && echo "ACCESSIBLE" || echo "BLOCKED/TIMEOUT (optional)")"
echo ""
if [ "$BACKEND_HTTP_STATUS" != "200" ]; then
    echo "⚠️  To fix backend access:"
    echo "   1. Open AWS Console → EC2 → Instances → Your Instance → Security → Security Groups"
    echo "   2. Edit inbound rules"
    echo "   3. Add: TCP port 8002 from $MY_IP/32"
    echo "   4. See AWS_SSM_RUNBOOK.md for detailed instructions"
fi

