#!/usr/bin/env bash
# Store current AWS credentials in SSM for ATP run-atp-command API.
# Run from a machine with AWS CLI configured (e.g. your Mac, same creds as deploy).
# The backend will use these to call SSM when instance metadata is unavailable in Docker.
#
# Usage: ./scripts/aws/store_aws_creds_for_atp_ssm.sh
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
PREFIX="/automated-trading-platform/prod"

if ! aws sts get-caller-identity >/dev/null 2>&1; then
  echo "ERROR: AWS CLI not configured or credentials invalid. Run: aws configure" >&2
  exit 1
fi

echo "Storing AWS credentials in SSM for ATP run-atp-command..."
echo "  Region: $REGION"
echo "  Prefix: $PREFIX"
echo ""

# Get credentials from env or from aws configure
AK="${AWS_ACCESS_KEY_ID:-$(aws configure get aws_access_key_id 2>/dev/null)}"
SK="${AWS_SECRET_ACCESS_KEY:-$(aws configure get aws_secret_access_key 2>/dev/null)}"

if [[ -z "$AK" || -z "$SK" ]]; then
  echo "ERROR: Could not get AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY." >&2
  echo "  Set them in env, or run: aws configure" >&2
  exit 1
fi

aws ssm put-parameter --name "${PREFIX}/aws_access_key_id" \
  --value "$AK" --type SecureString --overwrite --region "$REGION"
aws ssm put-parameter --name "${PREFIX}/aws_secret_access_key" \
  --value "$SK" --type SecureString --overwrite --region "$REGION"

echo "Done. Next: full deploy (render_runtime_env will pick them up)."
echo "  ./deploy_via_ssm.sh full   # or: bash scripts/aws/render_runtime_env.sh && docker compose --profile aws restart backend-aws"
