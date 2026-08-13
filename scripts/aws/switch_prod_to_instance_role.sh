#!/usr/bin/env bash
# Phase C — strip static AWS keys from prod env files and recreate backend-aws
# onto the instance role. Does not print secret values.
#
# Preconditions: Phase B succeeded (atp-backend-ec2-profile attached, IMDS hop limit 2).
#
# Run from operator workstation:
#   AWS_PROFILE=carlos-sso ./scripts/aws/switch_prod_to_instance_role.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_PROFILE="${AWS_PROFILE:-carlos-sso}"
export AWS_DEFAULT_REGION="$REGION"
INSTANCE_ID="i-087953603011543c5"
REMOTE="$ROOT/scripts/aws/switch_prod_to_instance_role.remote.sh"
ROLE_NAME="atp-backend-ec2-role"
PROFILE_NAME="atp-backend-ec2-profile"

if [[ ! -f "$REMOTE" ]]; then
  echo "FAIL: missing $REMOTE" >&2
  exit 1
fi

echo "=== Phase C: switch prod to instance role ==="
echo "Profile: $AWS_PROFILE  Region: $REGION"
echo ""

if ! ID_JSON=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: cannot assume AWS_PROFILE=$AWS_PROFILE. On the Mac: aws sso login --profile carlos-sso" >&2
  exit 1
fi
echo "Caller: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Arn'])" "$ID_JSON")"

echo "=== Guard: instance profile + IMDS hop limit ==="
PROF=$(aws ec2 describe-iam-instance-profile-associations \
  --filters "Name=instance-id,Values=$INSTANCE_ID" \
  --region "$REGION" \
  --query 'IamInstanceProfileAssociations[0].IamInstanceProfile.Arn' \
  --output text)
HOP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].MetadataOptions.HttpPutResponseHopLimit' \
  --output text)
echo "instance_profile_arn=$PROF"
echo "imds_hop_limit=$HOP"
if ! echo "$PROF" | grep -q "$PROFILE_NAME"; then
  echo "FAIL: PROD is not on $PROFILE_NAME. Run Phase B first: AWS_PROFILE=carlos-sso ./scripts/aws/create_atp_backend_ec2_role.sh" >&2
  exit 1
fi
if [[ "$HOP" != "2" ]]; then
  echo "FAIL: IMDS hop limit is $HOP (need 2 for Docker). Re-run Phase B script." >&2
  exit 1
fi

echo "=== SSM send-command (timeout 15m, live trading canary recreate) ==="
INPUT_FILE="$(mktemp)"
python3 - "$INSTANCE_ID" "$REMOTE" "$INPUT_FILE" <<'PY'
import json, sys
from pathlib import Path
instance_id, remote_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
script = Path(remote_path).read_text(encoding="utf-8")
payload = {
    "InstanceIds": [instance_id],
    "DocumentName": "AWS-RunShellScript",
    "TimeoutSeconds": 900,
    "Comment": "Phase C strip AWS keys and recreate backend-aws onto instance role",
    "Parameters": {"commands": [script]},
}
Path(out_path).write_text(json.dumps(payload), encoding="utf-8")
PY
trap 'rm -f "$INPUT_FILE"' EXIT

CMD_ID=$(aws ssm send-command \
  --cli-input-json "file://$INPUT_FILE" \
  --region "$REGION" \
  --query 'Command.CommandId' --output text)
echo "ssm_command_id=$CMD_ID"

STATUS="Pending"
for _ in $(seq 1 90); do
  sleep 10
  STATUS=$(aws ssm get-command-invocation \
    --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
    --query 'Status' --output text 2>/dev/null || echo Pending)
  echo "ssm_status=$STATUS"
  if [[ "$STATUS" == "Success" || "$STATUS" == "Failed" || "$STATUS" == "Cancelled" || "$STATUS" == "TimedOut" ]]; then
    break
  fi
done

OUT=$(aws ssm get-command-invocation \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query 'StandardOutputContent' --output text 2>/dev/null || true)
ERR=$(aws ssm get-command-invocation \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query 'StandardErrorContent' --output text 2>/dev/null || true)
echo "=== remote stdout ==="
echo "$OUT"
if [[ -n "$ERR" && "$ERR" != "None" ]]; then
  echo "=== remote stderr ==="
  echo "$ERR"
fi

if [[ "$STATUS" != "Success" ]]; then
  echo "FAIL: Phase C remote script status=$STATUS. Trading: if backend-aws is unhealthy, recreate again with the pinned image; do not re-add the deleted access key." >&2
  exit 1
fi

echo "=== Delete SSM static-key parameters (names only; never print values) ==="
for PARAM in \
  /automated-trading-platform/prod/aws_access_key_id \
  /automated-trading-platform/prod/aws_secret_access_key
do
  if aws ssm delete-parameter --name "$PARAM" --region "$REGION" >/dev/null 2>&1; then
    echo "deleted $PARAM"
  else
    echo "absent_or_already_deleted $PARAM"
  fi
done

echo ""
echo "PASS: Phase C complete. backend-aws should now assume $ROLE_NAME."
echo "Bedrock Operation not allowed is expected until AWS lifts the account restriction."
echo ""
echo "=== Phase D (Mac, show-then-run) — not executed from this script ==="
echo "1) Delete leaked-key backup:"
echo "     rm -f ~/.aws/credentials.bak"
echo "2) Strip AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY from the local copy of secrets/runtime.env"
echo "3) Search with bash (list only). Do not paste a for-loop into zsh:"
echo "     export REVOKED_AWS_ACCESS_KEY_ID='AKIA...'"
echo "     bash scripts/aws/search_revoked_access_key_id.sh"
echo "Leave jarvis-lab-bedrock keys on LAB untouched."
