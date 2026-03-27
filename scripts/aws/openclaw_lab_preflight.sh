#!/usr/bin/env bash
# OpenClaw LAB preflight: run checks on LAB via SSM (Docker, repo, .env.lab).
# Usage: ./scripts/aws/openclaw_lab_preflight.sh
# Requires: AWS CLI, SSM access to LAB instance.
set -euo pipefail

LAB_INSTANCE_ID="${1:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "=== OpenClaw LAB preflight (instance $LAB_INSTANCE_ID) ==="

STATUS=$(aws ssm describe-instance-information \
  --filters "Key=InstanceIds,Values=$LAB_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' \
  --output text 2>/dev/null || echo "None")
if [ "$STATUS" != "Online" ]; then
  echo "  SSM: $STATUS (need Online). Connect via Session Manager and follow docs/openclaw/RUNBOOK_OPENCLAW_LAB.md"
  exit 1
fi
echo "  SSM: $STATUS"

CMD_ID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["docker --version 2>/dev/null || echo no-docker","docker compose version 2>/dev/null | head -1 || echo no-compose","test -d /home/ubuntu/crypto-2.0/.git && echo repo-ok || echo repo-missing","test -f /home/ubuntu/crypto-2.0/.env.lab && echo envlab-ok || echo envlab-missing","test -r /home/ubuntu/secrets/openclaw_token && echo token-ok || echo token-missing","docker ps -q -f name=openclaw 2>/dev/null | wc -l"]' \
  --region "$REGION" \
  --query 'Command.CommandId' \
  --output text)
echo "  CommandId: $CMD_ID"
sleep 4
aws ssm get-command-invocation \
  --command-id "$CMD_ID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --query 'StandardOutputContent' \
  --output text | sed 's/^/  /'

echo "=== Done. Next: docs/openclaw/RUNBOOK_OPENCLAW_LAB.md"
