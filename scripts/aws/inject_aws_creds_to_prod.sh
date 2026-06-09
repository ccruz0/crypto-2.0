#!/usr/bin/env bash
# Inject AWS credentials into PROD runtime.env for run-atp-command.
# The instance has no AWS CLI, so render_runtime_env can't fetch from SSM.
# This script fetches locally and appends via SSM send-command.
#
# Usage: ./scripts/aws/inject_aws_creds_to_prod.sh
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
INSTANCE_ID="i-087953603011543c5"
PREFIX="/automated-trading-platform/prod"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "ERROR: AWS CLI not configured. Run: aws configure" >&2
  exit 1
fi

AK=$(aws ssm get-parameter --name "${PREFIX}/aws_access_key_id" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null || true)
SK=$(aws ssm get-parameter --name "${PREFIX}/aws_secret_access_key" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null || true)

if [[ -z "$AK" || -z "$SK" ]]; then
  echo "ERROR: Could not fetch credentials from SSM. Run store_aws_creds_for_atp_ssm.sh first." >&2
  exit 1
fi

# Base64 encode to safely pass via SSM command (avoids shell escaping)
B64_AK=$(echo -n "$AK" | base64 | tr -d '\n')
B64_SK=$(echo -n "$SK" | base64 | tr -d '\n')

echo "Injecting AWS credentials into PROD runtime.env..."

CMD="cd /home/ubuntu/crypto-2.0 || exit 1
grep -v '^AWS_ACCESS_KEY_ID=' secrets/runtime.env 2>/dev/null | grep -v '^AWS_SECRET_ACCESS_KEY=' | grep -v '^AWS_DEFAULT_REGION=' > secrets/runtime.env.tmp || cp secrets/runtime.env secrets/runtime.env.tmp
mv secrets/runtime.env.tmp secrets/runtime.env
echo 'AWS_ACCESS_KEY_ID='\$(echo $B64_AK | base64 -d) >> secrets/runtime.env
echo 'AWS_SECRET_ACCESS_KEY='\$(echo $B64_SK | base64 -d) >> secrets/runtime.env
echo 'AWS_DEFAULT_REGION=ap-southeast-1' >> secrets/runtime.env
docker compose --profile aws restart backend-aws"

CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[\"$CMD\"]" \
  --region "$REGION" \
  --timeout-seconds 120 \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $CMD_ID"
echo "Waiting 90s for restart..."
sleep 90
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' --output text 2>&1

echo ""
echo "Testing run-atp-command from instance..."
TEST_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["cd /home/ubuntu/crypto-2.0 && set -a && . secrets/runtime.env 2>/dev/null; set +a; curl -sS -X POST http://127.0.0.1:8002/api/agent/run-atp-command -H \"Authorization: Bearer ${OPENCLAW_API_TOKEN}\" -H \"Content-Type: application/json\" -d '\''{\"command\": \"docker compose --profile aws ps\"}'\''"]' \
  --region "$REGION" \
  --timeout-seconds 90 \
  --query 'Command.CommandId' \
  --output text)
sleep 75
aws ssm get-command-invocation --command-id "$TEST_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query 'StandardOutputContent' --output text 2>&1
