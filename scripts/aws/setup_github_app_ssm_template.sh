#!/usr/bin/env bash
# Write GitHub App credentials to AWS SSM Parameter Store (PROD path).
# Operator-run only. Never executed automatically by deploy tooling.
#
# Required environment variables:
#   GITHUB_APP_ID_VALUE              numeric GitHub App ID
#   GITHUB_APP_INSTALLATION_ID_VALUE numeric installation ID for ccruz0/crypto-2.0
#   GITHUB_APP_PRIVATE_KEY_B64_FILE  path to a file containing the base64-encoded
#                                    PEM private key (single line, no headers)
# Optional:
#   AWS_REGION   defaults to ap-southeast-1
#   DRY_RUN=1    print the aws commands that would run (secrets masked); write nothing
#
# Security: the private key value is never echoed. After writing, only parameter
# names, types, and versions are printed.

set -euo pipefail
set +x 2>/dev/null || true

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
DRY_RUN="${DRY_RUN:-0}"

SSM_APP_ID="/automated-trading-platform/prod/github_app/app_id"
SSM_INSTALLATION_ID="/automated-trading-platform/prod/github_app/installation_id"
SSM_PRIVATE_KEY_B64="/automated-trading-platform/prod/github_app/private_key_b64"

fail() { echo "ERROR: $*" >&2; exit 1; }

# --- Fail fast on missing env vars ---
[[ -n "${GITHUB_APP_ID_VALUE:-}" ]] || fail "GITHUB_APP_ID_VALUE is not set"
[[ -n "${GITHUB_APP_INSTALLATION_ID_VALUE:-}" ]] || fail "GITHUB_APP_INSTALLATION_ID_VALUE is not set"
[[ -n "${GITHUB_APP_PRIVATE_KEY_B64_FILE:-}" ]] || fail "GITHUB_APP_PRIVATE_KEY_B64_FILE is not set"

# --- Validate inputs ---
[[ "$GITHUB_APP_ID_VALUE" =~ ^[0-9]+$ ]] \
  || fail "GITHUB_APP_ID_VALUE must be numeric (got a non-numeric value)"
[[ "$GITHUB_APP_INSTALLATION_ID_VALUE" =~ ^[0-9]+$ ]] \
  || fail "GITHUB_APP_INSTALLATION_ID_VALUE must be numeric (got a non-numeric value)"
[[ -f "$GITHUB_APP_PRIVATE_KEY_B64_FILE" ]] \
  || fail "private key b64 file not found: $GITHUB_APP_PRIVATE_KEY_B64_FILE"
[[ -s "$GITHUB_APP_PRIVATE_KEY_B64_FILE" ]] \
  || fail "private key b64 file is empty: $GITHUB_APP_PRIVATE_KEY_B64_FILE"

# Sanity: file should decode to a PEM private key (check header only; never print key material)
if ! base64 -d < "$GITHUB_APP_PRIVATE_KEY_B64_FILE" 2>/dev/null | head -1 | grep -q "PRIVATE KEY"; then
  fail "file does not look like a base64-encoded PEM private key (decode check failed)"
fi

command -v aws >/dev/null 2>&1 || fail "aws CLI not found"

echo "Region: $AWS_REGION"
echo "Target parameters:"
echo "  $SSM_APP_ID (String)"
echo "  $SSM_INSTALLATION_ID (String)"
echo "  $SSM_PRIVATE_KEY_B64 (SecureString)"
echo

if [[ "$DRY_RUN" == "1" ]]; then
  echo "DRY_RUN=1 — no parameters will be written. Commands that would run:"
  echo
  echo "aws ssm put-parameter --region $AWS_REGION --name $SSM_APP_ID --value '$GITHUB_APP_ID_VALUE' --type String --overwrite"
  echo "aws ssm put-parameter --region $AWS_REGION --name $SSM_INSTALLATION_ID --value '$GITHUB_APP_INSTALLATION_ID_VALUE' --type String --overwrite"
  echo "aws ssm put-parameter --region $AWS_REGION --name $SSM_PRIVATE_KEY_B64 --value '***MASKED (file://$GITHUB_APP_PRIVATE_KEY_B64_FILE)***' --type SecureString --overwrite"
  echo
  echo "Dry run complete. Re-run without DRY_RUN=1 to write."
  exit 0
fi

aws sts get-caller-identity >/dev/null 2>&1 || fail "AWS credentials unavailable (aws sts get-caller-identity failed)"

put_param() {
  # $1 name, $2 type, $3 value or file:// URI (secret values never echoed;
  # file:// is expanded by the AWS CLI itself, keeping the key out of argv)
  local name="$1" type="$2" value="$3" version
  version="$(aws ssm put-parameter \
    --region "$AWS_REGION" \
    --name "$name" \
    --value "$value" \
    --type "$type" \
    --overwrite \
    --query 'Version' --output text)" \
    || fail "failed to write $name"
  echo "  WROTE: $name type=$type version=$version"
}

echo "Writing parameters..."
put_param "$SSM_APP_ID" "String" "$GITHUB_APP_ID_VALUE"
put_param "$SSM_INSTALLATION_ID" "String" "$GITHUB_APP_INSTALLATION_ID_VALUE"
# Key is loaded by the AWS CLI directly from the file (file:// URI) so the
# secret value never appears in CLI argv, shell history, or process listings.
put_param "$SSM_PRIVATE_KEY_B64" "SecureString" "file://$GITHUB_APP_PRIVATE_KEY_B64_FILE"

echo
echo "Done. Verify presence (names/types only):"
aws ssm describe-parameters \
  --region "$AWS_REGION" \
  --parameter-filters "Key=Name,Option=BeginsWith,Values=/automated-trading-platform/prod/github_app/" \
  --query 'Parameters[].{Name:Name,Type:Type,Version:Version}' \
  --output table

echo
echo "Next: on PROD EC2 run scripts/aws/render_and_recreate_backend_safe.sh"
