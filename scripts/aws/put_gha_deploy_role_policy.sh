#!/usr/bin/env bash
# Apply the repo gha-deploy-frontend inline policy (OIDC). Does not create keys.
#
# Run from the operator Mac BEFORE merging the GHA OIDC workflow PR, so
# Runtime Guard / Sentinel on main do not lose SSM DescribeInstanceInformation.
#
#   AWS_PROFILE=carlos-sso ./scripts/aws/put_gha_deploy_role_policy.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_PROFILE="${AWS_PROFILE:-carlos-sso}"
export AWS_DEFAULT_REGION="$REGION"
ROLE_NAME="gha-deploy-frontend"
POLICY_NAME="gha-deploy-frontend-perms"
POLICY_FILE="$ROOT/ci-cd/iam/policy-gha-deploy-frontend.json"

if [[ ! -f "$POLICY_FILE" ]]; then
  echo "FAIL: missing $POLICY_FILE" >&2
  exit 1
fi

echo "=== Put inline policy $POLICY_NAME on $ROLE_NAME ==="
if ! ID_JSON=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: cannot assume AWS_PROFILE=$AWS_PROFILE. On the Mac: aws sso login --profile carlos-sso" >&2
  exit 1
fi
echo "Caller: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Arn'])" "$ID_JSON")"

aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$POLICY_NAME" \
  --policy-document "file://$POLICY_FILE"

echo "PASS: $ROLE_NAME inline policy updated from $POLICY_FILE"
echo "GitHub secret AWS_DEPLOY_ROLE_ARN must remain arn:aws:iam::634531197711:role/gha-deploy-frontend"
echo "After all workflows on main use OIDC, delete GitHub Actions secrets AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY."
