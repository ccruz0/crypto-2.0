#!/bin/bash

COMMAND_ID="caadf7f5-48a8-4595-b641-668f8a567e6f"
INSTANCE_ID="i-08726dc37133b2454"
REGION="ap-southeast-1"

echo "📊 Checking deployment status..."
echo "Command ID: $COMMAND_ID"
echo ""

RESULT=$(aws ssm get-command-invocation \
    --command-id $COMMAND_ID \
    --instance-id $INSTANCE_ID \
    --region $REGION \
    --output json 2>&1)

STATUS=$(echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['Status'])" 2>/dev/null || echo "Unknown")

echo "Status: $STATUS"
echo ""

if [ "$STATUS" = "Success" ]; then
    echo "✅ Deployment completed successfully!"
    echo ""
    echo "Output:"
    echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['StandardOutputContent'])" 2>/dev/null || echo "$RESULT"
elif [ "$STATUS" = "Failed" ]; then
    echo "❌ Deployment failed!"
    echo ""
    echo "Error:"
    echo "$RESULT" | python3 -c "import sys, json; print(json.load(sys.stdin)['StandardErrorContent'])" 2>/dev/null || echo "$RESULT"
elif [ "$STATUS" = "InProgress" ]; then
    echo "⏳ Deployment still in progress..."
    echo "Docker build can take 5-10 minutes. Please wait."
else
    echo "Status: $STATUS"
    echo ""
    echo "Full response:"
    echo "$RESULT" | python3 -m json.tool 2>/dev/null || echo "$RESULT"
fi
