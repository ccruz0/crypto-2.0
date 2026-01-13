#!/bin/bash
# Verify what the SSM port-forward is hitting

set -e

INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "🔍 Verifying SSM Port-Forward Backend"
echo "===================================="
echo ""

# Check if port-forward is active
echo "1. Checking if port-forward is active..."
if curl -sS --max-time 3 http://localhost:8002/api/health > /dev/null 2>&1; then
    echo "✅ Port-forward is active (localhost:8002 is reachable)"
else
    echo "❌ Port-forward is NOT active"
    echo "   Start SSM port-forward first:"
    echo "   aws ssm start-session --target $INSTANCE_ID --document-name AWS-StartPortForwardingSessionToRemoteHost --parameters '{\"host\":[\"127.0.0.1\"],\"portNumber\":[\"8002\"],\"localPortNumber\":[\"8002\"]}'"
    exit 1
fi
echo ""

# Check whoami endpoint
echo "2. Checking whoami endpoint..."
WHOAMI=$(curl -sS --max-time 5 "http://localhost:8002/api/diagnostics/whoami" 2>/dev/null || echo "NOT_FOUND")
if [ "$WHOAMI" = "NOT_FOUND" ]; then
    echo "❌ whoami endpoint not found (404) - backend does NOT include the fix"
    echo "   Deployment required"
else
    echo "✅ whoami endpoint exists"
    echo "$WHOAMI" | python3 -m json.tool 2>/dev/null || echo "$WHOAMI"
fi
echo ""

# Check what's running on the instance
echo "3. Checking what's running on instance port 8002..."
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "echo \"=== Docker Containers ===\"",
        "docker compose --profile aws ps 2>/dev/null || docker ps --format \"table {{.Names}}\\t{{.Image}}\\t{{.Ports}}\"",
        "echo \"\"",
        "echo \"=== Process on Port 8002 ===\"",
        "sudo lsof -i :8002 2>/dev/null || netstat -tlnp 2>/dev/null | grep :8002 || echo \"No process found\"",
        "echo \"\"",
        "echo \"=== Backend Container Info ===\"",
        "CONTAINER=$(docker compose --profile aws ps -q backend-aws 2>/dev/null || docker ps -q --filter \"name=backend-aws\" | head -1)",
        "if [ -n \"$CONTAINER\" ]; then",
        "  echo \"Container ID: $CONTAINER\"",
        "  docker inspect $CONTAINER --format \"Image: {{.Config.Image}}\" 2>/dev/null || echo \"Could not inspect\"",
        "  docker inspect $CONTAINER --format \"Env: {{range .Config.Env}}{{println .}}{{end}}\" 2>/dev/null | grep -E \"(ENVIRONMENT|RUNTIME_ORIGIN|ATP_GIT_SHA)\" || echo \"No version info in env\"",
        "else",
        "  echo \"❌ Backend container not found\"",
        "fi"
    ]' \
    --query 'Command.CommandId' \
    --output text)

echo "✅ Command sent, waiting for output..."
sleep 5

OUTPUT=$(aws ssm get-command-invocation \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --command-id "$COMMAND_ID" \
    --query 'StandardOutputContent' \
    --output text 2>/dev/null)

echo "$OUTPUT"
echo ""

# Test portfolio snapshot
echo "4. Testing portfolio snapshot endpoint..."
SNAPSHOT=$(curl -sS --max-time 10 "http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM" 2>/dev/null || echo "FAILED")
if [ "$SNAPSHOT" = "FAILED" ]; then
    echo "❌ Portfolio snapshot endpoint failed"
else
    OK=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('ok', False))" 2>/dev/null || echo "false")
    SOURCE=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('portfolio_source', 'N/A'))" 2>/dev/null || echo "N/A")
    POSITIONS=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(len(d.get('positions', [])))" 2>/dev/null || echo "0")
    ERRORS=$(echo "$SNAPSHOT" | python3 -c "import sys, json; d=json.load(sys.stdin); errs=d.get('errors', []); print('; '.join(errs) if errs else 'none')" 2>/dev/null || echo "unknown")
    
    echo "Result:"
    echo "  ok: $OK"
    echo "  portfolio_source: $SOURCE"
    echo "  positions: $POSITIONS"
    echo "  errors: $ERRORS"
    
    if [ "$OK" = "True" ] && [ "$SOURCE" = "crypto_com" ] && [ "$POSITIONS" -gt 0 ]; then
        echo "✅ Portfolio snapshot is working correctly!"
    elif [ "$OK" = "True" ] && [ "$SOURCE" = "crypto_com" ]; then
        echo "⚠️  Portfolio snapshot works but no positions (empty account?)"
    elif echo "$ERRORS" | grep -q "40101"; then
        echo "❌ Auth error 40101 - credentials issue"
    else
        echo "⚠️  Portfolio snapshot returned but not fully working"
    fi
    
    echo ""
    echo "Full response (first 100 lines):"
    echo "$SNAPSHOT" | python3 -m json.tool 2>/dev/null | head -100 || echo "$SNAPSHOT" | head -100
fi

echo ""
echo "✅ Verification complete!"


