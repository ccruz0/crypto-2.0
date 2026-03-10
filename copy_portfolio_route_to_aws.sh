#!/bin/bash
# Copy routes_portfolio.py directly to AWS and rebuild

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "📤 Copying routes_portfolio.py to AWS..."
echo ""

# Read file and base64 encode for transmission
FILE_CONTENT=$(base64 -i backend/app/api/routes_portfolio.py)

# Send file via SSM
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters "commands=[
        \"cd ~/automated-trading-platform\",
        \"mkdir -p backend/app/api\",
        \"echo '$FILE_CONTENT' | base64 -d > backend/app/api/routes_portfolio.py\",
        \"chmod 644 backend/app/api/routes_portfolio.py\",
        \"echo '✅ File copied'\",
        \"ls -la backend/app/api/routes_portfolio.py\",
        \"echo ''\",
        \"echo '🔨 Rebuilding backend...'\",
        \"docker compose --profile aws build backend-aws\",
        \"docker compose --profile aws up -d backend-aws\",
        \"sleep 25\",
        \"curl -s http://localhost:8002/api/health || echo 'Health check failed'\"
    ]" \
    --query 'Command.CommandId' \
    --output text)

echo "✅ Command sent (ID: $COMMAND_ID)"
echo "⏳ Waiting for deployment (90 seconds)..."

sleep 90

OUTPUT=$(aws ssm get-command-invocation \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --command-id "$COMMAND_ID" \
    --query 'StandardOutputContent' \
    --output text 2>/dev/null)

echo "$OUTPUT"

echo ""
echo "🧪 Testing endpoint..."
sleep 5
curl -sS --max-time 10 "http://localhost:8002/api/portfolio/snapshot?exchange=CRYPTO_COM" | python3 -m json.tool 2>/dev/null | head -50 || echo "Still failing"


