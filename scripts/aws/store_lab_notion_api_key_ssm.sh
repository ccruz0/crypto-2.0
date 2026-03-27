#!/usr/bin/env bash
# Create or update the LAB Notion API key in SSM so lab_notion_oneliner_ssm.sh can use it.
# Run from your machine (AWS CLI). The LAB instance role must have ssm:GetParameter (and
# kms:Decrypt if using a custom KMS key) for this parameter.
#
# Usage: NOTION_API_KEY=secret_xxx ./scripts/aws/store_lab_notion_api_key_ssm.sh
#        ./scripts/aws/store_lab_notion_api_key_ssm.sh   # will prompt if not in env

set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
SSM_NOTION_KEY="/automated-trading-platform/lab/notion/api_key"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "ERROR: AWS CLI not configured or credentials invalid. Run: aws configure" >&2
  exit 1
fi

if [[ -z "${NOTION_API_KEY:-}" ]]; then
  echo "NOTION_API_KEY not set. Paste your Notion integration secret (starts with secret_ or nts_):"
  read -rs NOTION_API_KEY
  echo ""
  if [[ -z "$NOTION_API_KEY" ]]; then
    echo "ERROR: No value provided." >&2
    exit 1
  fi
fi

echo "Storing Notion API key in SSM for LAB..."
echo "  Parameter: $SSM_NOTION_KEY"
echo "  Region: $REGION"
aws ssm put-parameter \
  --name "$SSM_NOTION_KEY" \
  --value "$NOTION_API_KEY" \
  --type SecureString \
  --overwrite \
  --region "$REGION"

echo "Done. Ensure LAB instance role has ssm:GetParameter for $SSM_NOTION_KEY, then run:"
echo "  BACKEND=/home/ubuntu/crypto-2.0 LAB_INSTANCE_ID=i-0d82c172235770a0d AWS_REGION=ap-southeast-1 ./scripts/aws/lab_notion_oneliner_ssm.sh"
