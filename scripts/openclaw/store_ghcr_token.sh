#!/usr/bin/env bash
# Store GHCR token in AWS Parameter Store so LAB can docker login without typing it.
# Run once on your Mac (after setting GHCR_TOKEN).
# Usage: export GHCR_TOKEN='ghp_xxx'; ./scripts/openclaw/store_ghcr_token.sh
set -e

AWS_REGION="${AWS_REGION:-ap-southeast-1}"

if [[ -z "${GHCR_TOKEN:-}" ]]; then
  echo "Set GHCR_TOKEN first: export GHCR_TOKEN='ghp_your_token'" 1>&2
  exit 1
fi

aws ssm put-parameter \
  --name /openclaw/ghcr-token \
  --value "$GHCR_TOKEN" \
  --type SecureString \
  --region "$AWS_REGION" \
  --overwrite

echo "Token stored. On LAB (inside SSM session) run:"
echo ""
echo "  aws ssm get-parameter --name /openclaw/ghcr-token --with-decryption --query Parameter.Value --output text --region $AWS_REGION | sudo docker login ghcr.io -u ccruz0 --password-stdin"
echo ""
