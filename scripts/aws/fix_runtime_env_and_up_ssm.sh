#!/bin/bash
# Fix secrets/runtime.env permissions on EC2 and run docker compose up. Uses SSM (no SSH key needed).
# Run from repo root with AWS CLI configured. If SSM shows ConnectionLost, run the commands manually on EC2.
set -e

INSTANCE_ID="${ATP_EC2_INSTANCE_ID:-i-087953603011543c5}"
REGION="${ATP_AWS_REGION:-ap-southeast-1}"

PING=$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "None")
if [ "$PING" != "Online" ]; then
    echo "Instance $INSTANCE_ID SSM PingStatus=$PING (need Online). Run these commands on EC2 instead:"
    echo "  cd /home/ubuntu/automated-trading-platform"
    echo "  sudo chown ubuntu:ubuntu secrets/runtime.env && chmod 600 secrets/runtime.env"
    echo "  docker compose --profile aws up -d"
    exit 1
fi

echo "Fix runtime.env permissions and docker compose up via SSM (instance=$INSTANCE_ID)"
COMMAND_ID=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=[
        "cd /home/ubuntu/automated-trading-platform",
        "ls -la secrets/runtime.env",
        "sudo chown ubuntu:ubuntu secrets/runtime.env",
        "chmod 600 secrets/runtime.env",
        "docker compose --profile aws up -d",
        "echo Done.",
        "docker compose --profile aws ps"
    ]' \
    --query 'Command.CommandId' \
    --output text)

if [ -z "$COMMAND_ID" ]; then
    echo "Failed to send SSM command"
    exit 1
fi

echo "Command ID: $COMMAND_ID — waiting for execution..."
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION" || true

echo ""
echo "=== Output ==="
aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query '[Status, StandardOutputContent, StandardErrorContent]' --output text | tr '\t' '\n'
echo ""
