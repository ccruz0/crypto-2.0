#!/usr/bin/env bash
# Add GITHUB_TOKEN to .env.aws on EC2 and restart backend.
# Usage: GITHUB_TOKEN=ghp_xxx ./deploy_github_token_ssm.sh
# Or: uses /openclaw/github-token from SSM if GITHUB_TOKEN not set.
set -euo pipefail

INSTANCE_ID="i-087953603011543c5"
REGION="ap-southeast-1"
PROJECT_DIR="automated-trading-platform"

# Get token: env var, or fetch from SSM
if [[ -n "${GITHUB_TOKEN:-}" ]]; then
  TOKEN="$GITHUB_TOKEN"
  echo "Using GITHUB_TOKEN from environment"
else
  TOKEN=$(aws ssm get-parameter --name /automated-trading-platform/prod/github_token --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || aws ssm get-parameter --name /openclaw/github-token --with-decryption --query 'Parameter.Value' --output text 2>/dev/null || true)
  if [[ -z "$TOKEN" ]]; then
    echo "❌ GITHUB_TOKEN not set and could not fetch from SSM"
    echo "Usage: GITHUB_TOKEN=ghp_xxx ./deploy_github_token_ssm.sh"
    exit 1
  fi
  echo "Using token from SSM"
fi

# Escape for JSON in SSM parameters
TOKEN_ESC="${TOKEN//\\/\\\\}"
TOKEN_ESC="${TOKEN_ESC//\"/\\\"}"

echo "Adding GITHUB_TOKEN to .env.aws on EC2 and restarting backend..."
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "commands=[
    \"cd /home/ubuntu/$PROJECT_DIR\",
    \"if grep -q '^GITHUB_TOKEN=' .env.aws; then sed -i 's|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$TOKEN_ESC|' .env.aws; else echo 'GITHUB_TOKEN=$TOKEN_ESC' >> .env.aws; fi\",
    \"grep -c '^GITHUB_TOKEN=' .env.aws || true\",
    \"docker compose --profile aws restart backend-aws\",
    \"sleep 8\",
    \"docker compose --profile aws logs backend-aws --tail=5\"
  ]" \
  --region "$REGION" \
  --output json \
  --query 'Command.CommandId' \
  --output text)

echo "Command ID: $COMMAND_ID"
echo "Waiting for command to complete..."
aws ssm wait command-executed --command-id "$COMMAND_ID" --instance-id "$INSTANCE_ID" --region "$REGION"

OUTPUT=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' \
  --output text)

echo ""
echo "Status: $(echo "$OUTPUT" | cut -f1)"
echo "Output:"
echo "$OUTPUT" | cut -f2
echo ""
echo "✅ GITHUB_TOKEN deployed. Deploy approval from Telegram should now trigger the workflow."
