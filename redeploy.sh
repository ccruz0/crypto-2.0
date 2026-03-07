#!/bin/bash
# Full redeploy to EC2: pull code, rebuild backend + frontend, restart services and nginx.
# Run from your machine (requires AWS CLI and SSM access). Push your changes to origin main first.
set -e

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"
REPO_DIR="/home/ubuntu/automated-trading-platform"

if ! command -v aws &> /dev/null; then
    echo "❌ AWS CLI not found."
    exit 1
fi

echo "🚀 Redeploying backend + frontend on EC2"
echo "========================================"
echo "   Instance: $INSTANCE_ID"
echo "   Repo:     $REPO_DIR"
echo ""
echo "📤 Sending redeploy command (pull, build, up, nginx restart)..."

COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["set -e","cd /home/ubuntu/automated-trading-platform","git -c safe.directory=/home/ubuntu/automated-trading-platform pull origin main || true","docker compose --profile aws build --no-cache backend-aws frontend-aws","docker compose --profile aws up -d","sleep 5","sudo systemctl restart nginx || true","docker compose --profile aws ps","echo Done."]' \
    --region "$REGION" \
    --timeout-seconds 600 \
    --output text \
    --query 'Command.CommandId' 2>&1)

if [[ $COMMAND_ID == Error* ]] || [[ -z "$COMMAND_ID" ]]; then
    echo "❌ Failed: $COMMAND_ID"
    exit 1
fi

echo "✅ Command ID: $COMMAND_ID"
echo "⏳ Waiting up to 300s for pull + build + restart (no-cache build can take 5–10 min)..."
sleep 300

echo ""
echo "📊 Output:"
INVOCATION=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --output json 2>&1)
STATUS=$(echo "$INVOCATION" | grep -o '"Status": "[^"]*"' | cut -d'"' -f4)
DETAILS=$(echo "$INVOCATION" | grep -o '"StatusDetails": "[^"]*"' | cut -d'"' -f4)
STDOUT=$(echo "$INVOCATION" | grep -o '"StandardOutputContent": "[^"]*"' | cut -d'"' -f4 | sed 's/\\n/\n/g')
STDERR=$(echo "$INVOCATION" | grep -o '"StandardErrorContent": "[^"]*"' | cut -d'"' -f4 | sed 's/\\n/\n/g')

echo "Status: $STATUS"
[[ -n "$DETAILS" ]] && echo "Details: $DETAILS"
[[ -n "$STDOUT" ]] && echo "Stdout: $STDOUT"
[[ -n "$STDERR" ]] && echo "Stderr: $STDERR"

if [[ "$STATUS" == "Undeliverable" ]] || [[ "$STATUS" == "Failed" ]]; then
    echo ""
    echo "⚠️  Deploy did not complete (SSM: $STATUS). If Undeliverable, the instance may be unreachable via SSM."
    echo "   Run these commands on EC2 (SSH or new SSM session) to deploy manually:"
    echo ""
    echo "   cd $REPO_DIR"
    echo "   git pull origin main"
    echo "   docker compose --profile aws build --no-cache backend-aws frontend-aws"
    echo "   docker compose --profile aws up -d"
    echo "   sudo systemctl restart nginx"
    echo ""
    exit 1
fi

echo ""
echo "🎉 Redeploy completed. Verify: curl -s https://dashboard.hilovivo.com/api/ping_fast"
