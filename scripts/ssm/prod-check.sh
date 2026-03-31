#!/usr/bin/env bash
# Run /home/ubuntu/run_atp_checks.sh on PROD via SSM (from Mac or any host with AWS CLI).
# Usage: ./scripts/ssm/prod-check.sh
# Env: AWS_PROD_INSTANCE_ID (default i-087953603011543c5), AWS_REGION (default ap-southeast-1)
set -euo pipefail

INSTANCE_ID="${AWS_PROD_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
REMOTE_SCRIPT="/home/ubuntu/run_atp_checks.sh"

echo "==> SSM send-command → $INSTANCE_ID ($REGION)"
echo "==> Remote: $REMOTE_SCRIPT"

CMD_ID="$(
  aws ssm send-command \
    --instance-ids "$INSTANCE_ID" \
    --region "$REGION" \
    --document-name "AWS-RunShellScript" \
    --comment "ATP prod-check $(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    --parameters "{\"commands\":[\"bash ${REMOTE_SCRIPT}\"]}" \
    --output text \
    --query 'Command.CommandId'
)"

echo "==> CommandId: $CMD_ID"
echo "==> Waiting for completion (up to ~90s)..."
for _ in $(seq 1 30); do
  sleep 3
  STATUS="$(
    aws ssm get-command-invocation \
      --command-id "$CMD_ID" \
      --instance-id "$INSTANCE_ID" \
      --region "$REGION" \
      --query 'Status' \
      --output text 2>/dev/null || echo Pending
  )"
  case "$STATUS" in
    Success | Failed | Cancelled | TimedOut) break ;;
  esac
done

aws ssm get-command-invocation \
  --command-id "$CMD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query '{Status:Status,ExitCode:ResponseCode,Stdout:StandardOutputContent,Stderr:StandardErrorContent}' \
  --output text

EXIT_CODE="$(
  aws ssm get-command-invocation \
    --command-id "$CMD_ID" \
    --instance-id "$INSTANCE_ID" \
    --region "$REGION" \
    --query 'ResponseCode' \
    --output text
)"
# SSM uses -1 when the agent has not reported an exit code yet.
if [[ -z "$EXIT_CODE" || "$EXIT_CODE" == "-1" ]]; then
  echo "==> prod-check: no final exit code (Status=$STATUS); inspect output above" >&2
  exit 1
fi
if [[ "$EXIT_CODE" != "0" ]]; then
  echo "==> prod-check: remote exit code $EXIT_CODE" >&2
  exit 1
fi
