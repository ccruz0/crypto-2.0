#!/usr/bin/env bash
# Install OpenClaw update daemon on LAB via SSM, then recreate the container.
# Usage: ./scripts/openclaw/install_openclaw_update_daemon_via_ssm.sh
#
# Requires: AWS credentials, LAB instance online, repo on main with the new files.
set -e

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
REPO_ON_LAB="${REPO_ON_LAB:-/home/ubuntu/automated-trading-platform}"

echo "=== Installing OpenClaw update daemon on LAB ($LAB_INSTANCE_ID) ==="

REPO_ESC=$(echo "$REPO_ON_LAB" | sed 's/"/\\"/g')
params="{\"commands\":[\"set -e\",\"cd $REPO_ESC\",\"git -c safe.directory=$REPO_ESC pull origin main 2>/dev/null || true\",\"sudo bash scripts/openclaw/install_openclaw_update_daemon.sh\",\"cd $REPO_ESC && sudo docker compose -f docker-compose.openclaw.yml up -d --force-recreate\",\"sleep 5\",\"sudo systemctl status openclaw-update-daemon --no-pager\",\"curl -s http://127.0.0.1:19999/health || echo health_check_failed\"]}"

cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$params" \
  --timeout-seconds 120 \
  --output text --query 'Command.CommandId')

echo "CommandId: $cmd_id"
echo "Waiting 90s for commands to complete..."
sleep 90

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
