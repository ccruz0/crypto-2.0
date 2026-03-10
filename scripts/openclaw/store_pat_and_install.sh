#!/usr/bin/env bash
# DEPRECATED: PAT in SSM is discouraged. Use prompt_pat_and_install.sh (SSH-only, token only on LAB).
# Run from your Mac: stores GitHub PAT in SSM and triggers full OpenClaw install on LAB.
# Usage: OPENCLAW_PAT=ghp_xxx ./scripts/openclaw/store_pat_and_install.sh
set -e
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${REGION:-ap-southeast-1}"

if [ -z "${OPENCLAW_PAT-}" ]; then
  if [ -f .openclaw_pat ]; then
    OPENCLAW_PAT=$(cat .openclaw_pat)
  elif [ -f ~/.openclaw_pat ]; then
    OPENCLAW_PAT=$(cat ~/.openclaw_pat)
  fi
fi
if [ -z "${OPENCLAW_PAT-}" ]; then
  echo "Set OPENCLAW_PAT or create .openclaw_pat with your GitHub fine-grained PAT, then re-run." >&2
  exit 1
fi

echo "Storing PAT in SSM (SecureString)..."
aws ssm put-parameter \
  --name /openclaw/lab/github_pat \
  --type SecureString \
  --value "$OPENCLAW_PAT" \
  --region "$REGION" \
  --overwrite

echo "Starting full install on LAB ($LAB_INSTANCE_ID)..."
CMD_ID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=["set -e","OPENCLAW_TOKEN=$(aws ssm get-parameter --name /openclaw/lab/github_pat --with-decryption --query Parameter.Value --output text)","export OPENCLAW_TOKEN","bash -c \"bash <(curl -sSL https://raw.githubusercontent.com/ccruz0/crypto-2.0/main/scripts/openclaw/install_on_lab.sh)\""]' \
  --output text \
  --query "Command.CommandId")

echo "CommandId: $CMD_ID"
echo "Check status: aws ssm get-command-invocation --command-id $CMD_ID --instance-id $LAB_INSTANCE_ID --region $REGION --query '[Status,StandardOutputContent,StandardErrorContent]' --output json"
echo "Waiting 60s then showing output..."
sleep 60
aws ssm get-command-invocation --command-id "$CMD_ID" --instance-id "$LAB_INSTANCE_ID" --region "$REGION" --query '[Status,StandardOutputContent,StandardErrorContent]' --output json
