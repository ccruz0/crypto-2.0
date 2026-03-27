#!/usr/bin/env bash
# Check if secrets/telegram_key exists on PROD EC2 and optionally print scp instructions.
# Run from your Mac (requires AWS CLI and SSM or SSH access to the instance).
#
# Usage:
#   ./scripts/aws/check_telegram_key_on_ec2.sh          # try SSM, then print manual commands
#   ./scripts/aws/check_telegram_key_on_ec2.sh --scp     # print scp command to copy key to local

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
SSH_USER="${EC2_SSH_USER:-ubuntu}"
# Default EC2 host (override if you use a different way to connect)
EC2_HOST="${EC2_HOST:-}"

# Try SSM first
STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "ConnectionLost")

if [[ "$STATUS" == "Online" ]]; then
  echo "=== Checking PROD (SSM) for secrets/telegram_key ==="
  OUT=$(aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["test -f /home/ubuntu/crypto-2.0/secrets/telegram_key && echo FOUND || echo NOT_FOUND","test -f /home/ubuntu/crypto-2.0/secrets/telegram_key && echo FOUND_CRYPTO || true","ls -la /home/ubuntu/crypto-2.0/secrets/telegram_key 2>/dev/null || ls -la /home/ubuntu/crypto-2.0/secrets/telegram_key 2>/dev/null || true"]' \
    --timeout-seconds 30 \
    --query 'Command.CommandId' --output text 2>/dev/null || true)
  if [[ -n "$OUT" && "$OUT" != Error* ]]; then
    sleep 3
    aws ssm get-command-invocation --command-id "$OUT" --instance-id "$INSTANCE_ID" --region "$REGION" \
      --query 'StandardOutputContent' --output text 2>/dev/null || true
  fi
else
  echo "SSM status: $STATUS (cannot run command from this host)."
fi

echo ""
echo "=== Manual check / copy from EC2 ==="
echo "1. Connect to PROD: AWS Console → EC2 → Instance $INSTANCE_ID → Connect (Session Manager or EC2 Instance Connect)."
echo "2. In the session, run:"
echo "   test -f /home/ubuntu/crypto-2.0/secrets/telegram_key && echo FOUND || test -f /home/ubuntu/crypto-2.0/secrets/telegram_key && echo FOUND || echo NOT_FOUND"
echo "   ls -la /home/ubuntu/crypto-2.0/secrets/telegram_key 2>/dev/null || ls -la /home/ubuntu/crypto-2.0/secrets/telegram_key 2>/dev/null"
echo "3. To copy the key to your Mac (from your Mac, after you have SSH or Session Manager plugin):"
echo "   aws ssm start-session --target $INSTANCE_ID --region $REGION --document-name AWS-StartNonInteractiveCommand --parameters command=\"cat /home/ubuntu/crypto-2.0/secrets/telegram_key\" 2>/dev/null | head -1"
echo "   Or via scp if you use SSH: scp ${SSH_USER}@<EC2_PUBLIC_IP>:/home/ubuntu/crypto-2.0/secrets/telegram_key $REPO_ROOT/secrets/telegram_key"
echo ""
echo "If FOUND, copy that file to: $REPO_ROOT/secrets/telegram_key (then chmod 600)."
