#!/bin/bash
# Script to verify commands are running on Mac (not EC2) and test external access
# Run this on your Mac to prove execution context and test external health endpoint
# This script is READ-ONLY: it does not make any changes

set -euo pipefail

echo "========================================="
echo "Mac vs EC2 Context Verification"
echo "========================================="
echo ""

echo "=== LOCAL MODE: Running on Mac ==="
echo ""

echo "1. System Information:"
echo "   Hostname: $(hostname)"
echo "   OS: $(uname -a)"
echo "   User: $(whoami)"
echo ""

echo "2. Public IP (from Mac):"
MAC_IP=$(curl -s https://api.ipify.org 2>/dev/null || \
  python3 -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())" 2>/dev/null || \
  python -c "import urllib.request; print(urllib.request.urlopen('https://api.ipify.org').read().decode())" 2>/dev/null || \
  echo "ERROR: Could not determine public IP")
echo "   Mac Public IP: $MAC_IP"
echo ""

echo "3. Checking for local Docker containers:"
echo "   Running: docker compose --profile aws ps"
echo ""
if cd ~/automated-trading-platform 2>/dev/null && docker compose --profile aws ps 2>/dev/null | head -20; then
    echo ""
    echo "   ⚠️  IMPORTANT: Docker containers listed above are LOCAL (running on this Mac)"
    echo "   ⚠️  These are NOT the EC2 containers"
    echo "   ✅ This PROVES commands are running on Mac, NOT on EC2"
    echo "   ✅ To access EC2 containers, you must use AWS SSM Session Manager"
else
    echo "   ⚠️  No local containers found (or docker compose not available)"
    echo "   This is expected if you don't run containers locally"
fi
echo ""

echo "4. Testing External Access (will timeout if Security Group not configured):"
echo "   Attempting: curl -m 5 -v http://54.254.150.31:8002/api/health"
echo "   (This will timeout/refuse if inbound rules are not set)"
echo ""
curl -m 5 -v http://54.254.150.31:8002/api/health 2>&1 || echo "   ⚠️  Connection failed (expected if Security Group doesn't allow your IP)"
echo ""

echo "5. Alternative EC2 Public IPs (if first one fails):"
echo "   Trying: 175.41.189.249:8002"
curl -m 5 -v http://175.41.189.249:8002/api/health 2>&1 || echo "   ⚠️  Connection failed (expected if Security Group doesn't allow your IP)"
echo ""

echo "========================================="
echo "Summary:"
echo "========================================="
echo "✅ Execution Context: LOCAL MODE (Mac)"
echo "✅ Mac Public IP: $MAC_IP"
echo "⚠️  External Access: Will fail until Security Group allows $MAC_IP/32 on port 8002"
echo ""
echo "Next Steps:"
echo "  1. Connect to EC2 via AWS SSM Session Manager (see AWS_SSM_RUNBOOK.md)"
echo "  2. Run scripts/verify_ec2_ip_and_health.sh on EC2"
echo "  3. Add Security Group inbound rules (see AWS_SSM_RUNBOOK.md)"
echo "  4. Test external access using scripts/verify_inbound_access_from_mac.sh"
