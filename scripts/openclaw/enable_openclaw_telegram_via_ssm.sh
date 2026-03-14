#!/usr/bin/env bash
# Run enable_openclaw_telegram.sh on LAB via SSM.
# Usage: ./scripts/openclaw/enable_openclaw_telegram_via_ssm.sh

set -e

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
# LAB repo path (not local Mac path)
REPO_ON_LAB="${REPO_ON_LAB:-/home/ubuntu/automated-trading-platform}"

echo "=== Enabling OpenClaw Telegram on LAB ($LAB_INSTANCE_ID) ==="
cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"export HOME=/root; git config --global --add safe.directory $REPO_ON_LAB; cd $REPO_ON_LAB && git stash -u 2>/dev/null || true && git pull origin main; sudo bash $REPO_ON_LAB/scripts/openclaw/enable_openclaw_telegram.sh\"]" \
  --output text --query 'Command.CommandId')

echo "CommandId: $cmd_id"
echo "Waiting 60s..."
sleep 60

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
