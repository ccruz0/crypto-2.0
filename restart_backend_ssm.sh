#!/bin/bash
# Quick Backend Restart Script using AWS SSM

set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"

echo "🚀 Restarting Backend via AWS SSM"
echo "=================================="
echo ""

# Check AWS CLI
if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI is not installed"
    exit 1
fi

echo "📤 Sending restart command to instance $INSTANCE_ID..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd ~/automated-trading-platform",
        "echo \"🔄 Restarting Docker backend...\"",
        "docker compose --profile aws restart backend-aws",
        "sleep 5",
        "echo \"✅ Checking status...\"",
        "docker compose --profile aws ps backend-aws",
        "echo \"\"",
        "echo \"🧪 Testing health endpoint...\"",
        "sleep 3",
        "curl -s http://localhost:8002/health || echo \"Health check failed\""
    ]' \
    --query 'Command.CommandId' \
    --output text)

if [ -z "$COMMAND_ID" ]; then
    echo "❌ Failed to send command"
    exit 1
fi

echo "✅ Command sent (ID: $COMMAND_ID)"
echo "⏳ Waiting for execution (this may take 30-60 seconds)..."
echo ""

# Wait and get output
for i in {1..60}; do
    STATUS=$(aws ssm get-command-invocation \
        --instance-id "$INSTANCE_ID" \
        --region "$REGION" \
        --command-id "$COMMAND_ID" \
        --query 'Status' \
        --output text 2>/dev/null || echo "InProgress")
    
    if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
        echo ""
        echo "📋 Command Output:"
        echo "=================="
        
        OUTPUT=$(aws ssm get-command-invocation \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" \
            --command-id "$COMMAND_ID" \
            --query 'StandardOutputContent' \
            --output text 2>/dev/null)
        
        ERROR=$(aws ssm get-command-invocation \
            --instance-id "$INSTANCE_ID" \
            --region "$REGION" \
            --command-id "$COMMAND_ID" \
            --query 'StandardErrorContent' \
            --output text 2>/dev/null)
        
        echo "$OUTPUT"
        if [ -n "$ERROR" ] && [ "$ERROR" != "None" ]; then
            echo ""
            echo "⚠️  Errors:"
            echo "$ERROR"
        fi
        
        if [ "$STATUS" = "Success" ]; then
            echo ""
            echo "✅ Backend restart completed!"
            echo ""
            echo "🧪 Testing external access..."
            sleep 2
            EXTERNAL=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "https://dashboard.hilovivo.com/api/monitoring/summary" 2>/dev/null || echo "000")
            if [ "$EXTERNAL" = "200" ]; then
                echo "✅ External access is working! (HTTP $EXTERNAL)"
            else
                echo "⚠️  External access shows HTTP $EXTERNAL (may need a few more seconds)"
            fi
        else
            echo ""
            echo "❌ Command failed. Check errors above."
        fi
        break
    fi
    
    if [ $((i % 5)) -eq 0 ]; then
        echo -n "."
    fi
    sleep 1
done

echo ""
echo "Done!"
















