#!/bin/bash
# Check deployment status

COMMAND_ID="${1:-aa64b511-3d0f-4a9f-ae3b-e47efcaf1df5}"
INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🔍 Checking deployment status..."
echo "Command ID: $COMMAND_ID"
echo ""

STATUS=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "Status" \
  --output text 2>/dev/null)

echo "Status: $STATUS"
echo ""

if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
    echo "=== OUTPUT ==="
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardOutputContent" \
      --output text
    
    echo ""
    echo "=== ERRORS (if any) ==="
    aws ssm get-command-invocation \
      --command-id "$COMMAND_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query "StandardErrorContent" \
      --output text
else
    echo "⏳ Deployment still in progress..."
    echo "   Run this script again in a minute to check status"
    echo ""
    echo "   ./check_deployment_status.sh $COMMAND_ID"
fi
