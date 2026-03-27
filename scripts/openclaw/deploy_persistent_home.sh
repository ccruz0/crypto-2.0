#!/usr/bin/env bash
# Deploy OpenClaw with persistent home directory on LAB via AWS SSM.
# Ensures /home/node/.openclaw survives container restarts (device pairing,
# gateway tokens, config).
#
# Usage: ./scripts/openclaw/deploy_persistent_home.sh

set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"

if ! command -v aws &>/dev/null; then
  echo "AWS CLI required. Install and configure aws cli."
  exit 1
fi

echo "=== Deploy OpenClaw persistent home via SSM (LAB $LAB_INSTANCE_ID) ==="

STATUS=$(aws ssm describe-instance-information --region "$AWS_REGION" \
  --filters "Key=InstanceIds,Values=$LAB_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
echo "SSM PingStatus: $STATUS"
if [[ "$STATUS" != "Online" ]]; then
  echo "LAB instance not Online for SSM. Check SSM agent or instance state."
  exit 1
fi

COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 120 \
  --parameters 'commands=[
    "set -eu",
    "echo \"=== Creating persistent home directory ===\"",
    "mkdir -p /opt/openclaw/home-data",
    "chown 1000:1000 /opt/openclaw/home-data",
    "echo \"=== Copying existing data if container is running ===\"",
    "if docker ps --format={{.Names}} | grep -q ^openclaw$; then docker cp openclaw:/home/node/.openclaw/. /opt/openclaw/home-data/ 2>/dev/null && echo \"Copied container home data\" || echo \"No data to copy from container\"; else echo \"Container not running, skipping container copy\"; fi",
    "if [ -f /opt/openclaw/openclaw.json ]; then cp /opt/openclaw/openclaw.json /opt/openclaw/home-data/ && echo \"Copied openclaw.json into home-data\"; else echo \"No /opt/openclaw/openclaw.json found, skipping\"; fi",
    "chown -R 1000:1000 /opt/openclaw/home-data",
    "echo \"=== Stopping old container ===\"",
    "cd /home/ubuntu/crypto-2.0",
    "docker compose -f docker-compose.openclaw.yml down || true",
    "docker rm -f openclaw 2>/dev/null || true",
    "echo \"=== Starting with persistent home mount ===\"",
    "docker compose -f docker-compose.openclaw.yml up -d",
    "echo \"=== Waiting 15s for startup ===\"",
    "sleep 15",
    "echo \"=== Container status ===\"",
    "docker compose -f docker-compose.openclaw.yml ps",
    "echo \"=== Recent logs ===\"",
    "docker logs openclaw --tail 30 2>&1 || true",
    "echo \"=== Persistent home contents ===\"",
    "ls -la /opt/openclaw/home-data/ || true",
    "echo \"=== Done ===\""
  ]' \
  --query 'Command.CommandId' \
  --output text)

if [[ -z "$COMMAND_ID" ]]; then
  echo "Failed to send SSM command."
  exit 1
fi

echo "Command ID: $COMMAND_ID"
echo "Waiting for result (up to 120s)..."
for i in $(seq 1 120); do
  S=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" || "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    break
  fi
  sleep 1
done

echo ""
echo "=== Stdout ==="
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardOutputContent' --output text 2>/dev/null || echo "(none)"

echo ""
echo "=== Stderr ==="
aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardErrorContent' --output text 2>/dev/null || echo "(none)"

FINAL_STATUS=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'Status' --output text 2>/dev/null)
echo ""
echo "Final status: $FINAL_STATUS"
