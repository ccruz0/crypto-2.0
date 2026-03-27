#!/bin/bash
# Verify Telegram config on EC2 via SSM.
# Checks: tg_enabled_aws (DB), RUN_TELEGRAM, RUN_TELEGRAM_POLLER.
# Uses docker exec; tg_enabled check requires deploy with verify_telegram_tg_enabled.py.
set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "🔍 Verifying Telegram config on EC2..."
echo ""

# SSM commands - must be valid JSON array (tg_enabled via Python after deploy; env vars always work)
PARAMS='{"commands":["cd /home/ubuntu/crypto-2.0 2>/dev/null || cd /home/ubuntu/crypto-2.0 || true","echo === RUN_TELEGRAM backend-aws ===","docker compose --profile aws exec -T backend-aws printenv RUN_TELEGRAM 2>/dev/null || true","echo","echo === RUN_TELEGRAM_POLLER canary ===","docker compose --profile aws exec -T backend-aws-canary printenv RUN_TELEGRAM_POLLER 2>/dev/null || true","echo","echo === tg_enabled_aws DB ===","docker compose --profile aws exec -T backend-aws python scripts/diag/verify_telegram_tg_enabled.py 2>/dev/null || echo (run after deploy)"]}'
CMD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "$PARAMS" \
  --region "$REGION" \
  --timeout-seconds 60 \
  --output text \
  --query 'Command.CommandId' 2>&1)

if [[ "$CMD_ID" == Error* ]] || [[ -z "$CMD_ID" ]]; then
  echo "❌ SSM failed: $CMD_ID"
  exit 1
fi

echo "Command ID: $CMD_ID"
echo "Waiting 25s..."
sleep 25

aws ssm get-command-invocation \
  --command-id "$CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query 'StandardOutputContent' \
  --output text 2>&1

echo ""
echo "✅ Done. tg_enabled_aws should be 'true', RUN_TELEGRAM=true, canary RUN_TELEGRAM_POLLER=false."
