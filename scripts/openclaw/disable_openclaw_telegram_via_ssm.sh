#!/usr/bin/env bash
# Run disable_openclaw_telegram.sh on LAB via SSM (drops OpenClaw Telegram polling; fixes 409 vs PROD backend-aws).
# Embeds the script with base64 so it runs even if the repo on LAB is sparse or paths differ.
#
# Usage: ./scripts/openclaw/disable_openclaw_telegram_via_ssm.sh

set -euo pipefail

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
REPO_ON_LAB="${REPO_ON_LAB:-/home/ubuntu/automated-trading-platform}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT_LOCAL="${SCRIPT_DIR}/disable_openclaw_telegram.sh"
if [[ ! -f "$SCRIPT_LOCAL" ]]; then
  echo "Missing $SCRIPT_LOCAL" >&2
  exit 1
fi

# Single line (SSM / JSON safe); Linux LAB: base64 -d
B64="$(base64 < "$SCRIPT_LOCAL" | tr -d '\n')"

echo "=== Disabling OpenClaw Telegram on LAB ($LAB_INSTANCE_ID) ==="

PARAMS_FILE="$(mktemp)"
trap 'rm -f "$PARAMS_FILE"' EXIT

jq -n \
  --arg repo "$REPO_ON_LAB" \
  --arg b64 "$B64" \
  '{
    commands: [
      "export HOME=/root",
      ("git config --global --add safe.directory " + $repo),
      ("cd " + $repo + " && git stash push -u -m openclaw-disable-tg 2>/dev/null || true"),
      ("cd " + $repo + " && git pull origin main 2>/dev/null || true"),
      ("echo " + $b64 + " | base64 -d > /tmp/disable_openclaw_telegram.sh"),
      "chmod +x /tmp/disable_openclaw_telegram.sh",
      ("sudo REPO=" + $repo + " bash /tmp/disable_openclaw_telegram.sh")
    ]
  }' > "$PARAMS_FILE"

cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --timeout-seconds 300 \
  --parameters "file://$PARAMS_FILE" \
  --output text --query 'Command.CommandId')

echo "CommandId: $cmd_id"
for i in $(seq 1 90); do
  st=$(aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$LAB_INSTANCE_ID" --region "$AWS_REGION" --query 'Status' --output text 2>/dev/null || echo Pending)
  if [[ "$st" == "Success" ]]; then
    echo ""
    aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$LAB_INSTANCE_ID" --region "$AWS_REGION" \
      --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
    exit 0
  fi
  if [[ "$st" == "Failed" || "$st" == "Cancelled" ]]; then
    echo "Status: $st"
    aws ssm get-command-invocation --command-id "$cmd_id" --instance-id "$LAB_INSTANCE_ID" --region "$AWS_REGION" \
      --query '[StandardOutputContent, StandardErrorContent]' --output text
    exit 1
  fi
  sleep 2
done
echo "Timeout waiting for SSM."
exit 1
