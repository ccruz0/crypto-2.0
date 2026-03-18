#!/usr/bin/env bash
# Build OpenClaw wrapper (with pydantic-settings) ON LAB via SSM and restart.
# Use when GHCR push fails — no need to push; build runs on LAB directly.
#
# Usage: ./scripts/openclaw/deploy_wrapper_build_on_lab_via_ssm.sh

set -e

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
# LAB may have automated-trading-platform or crypto-2.0; find and run do_wrapper_build_on_lab.sh
echo "==> Build OpenClaw wrapper on LAB ($LAB_INSTANCE_ID) and restart"
cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["sudo -u ubuntu bash -c \"cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 || exit 1 && git fetch origin main && git reset --hard origin/main\"","cd /home/ubuntu/automated-trading-platform 2>/dev/null || cd /home/ubuntu/crypto-2.0 && sudo bash scripts/openclaw/do_wrapper_build_on_lab.sh"]' \
  --timeout-seconds 900 \
  --output text --query 'Command.CommandId')

echo "CommandId: $cmd_id"
echo "Waiting 90s, then polling (build can take 5-10 min)..."
sleep 90

for i in 1 2 3 4 5 6 7 8 9 10; do
  status=$(aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$LAB_INSTANCE_ID" --region "$AWS_REGION" --query 'Status' --output text 2>/dev/null || echo "Unknown")
  echo "  Status: $status"
  if [[ "$status" == "Success" ]] || [[ "$status" == "Failed" ]] || [[ "$status" == "Cancelled" ]]; then
    break
  fi
  sleep 60
done

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
