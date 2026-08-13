#!/usr/bin/env bash
# Strip static AWS keys on LAB (i-0d82c172235770a0d) via SSM.
# Does not touch PROD. Does not print secret values.
#
# Preconditions: AWS_PROFILE=carlos-sso ./scripts/aws/create_atp_lab_ec2_role.sh
#
#   AWS_PROFILE=carlos-sso ./scripts/aws/switch_lab_to_instance_role.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_PROFILE="${AWS_PROFILE:-carlos-sso}"
export AWS_DEFAULT_REGION="$REGION"
INSTANCE_ID="i-0d82c172235770a0d"
PROD_ID="i-087953603011543c5"
REMOTE="$ROOT/scripts/aws/switch_lab_to_instance_role.remote.sh"
ROLE_NAME="atp-lab-ec2-role"
PROFILE_NAME="atp-lab-ec2-profile"

if [[ "$INSTANCE_ID" == "$PROD_ID" ]]; then
  echo "FAIL: refusing to target PROD" >&2
  exit 1
fi
if [[ ! -f "$REMOTE" ]]; then
  echo "FAIL: missing $REMOTE" >&2
  exit 1
fi

echo "=== Switch LAB to instance role ==="
if ! ID_JSON=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: cannot assume AWS_PROFILE=$AWS_PROFILE. On the Mac: aws sso login --profile carlos-sso" >&2
  exit 1
fi
echo "Caller: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Arn'])" "$ID_JSON")"

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
  echo "FAIL: LAB is not on $PROFILE_NAME. Run create_atp_lab_ec2_role.sh first." >&2
  exit 1
fi
if [[ "$HOP" != "2" ]]; then
  echo "FAIL: IMDS hop limit is $HOP (need 2 for Docker). Re-run create_atp_lab_ec2_role.sh." >&2
  exit 1
fi

INPUT_FILE="$(mktemp)"
python3 - "$INSTANCE_ID" "$REMOTE" "$INPUT_FILE" <<'PY'
import json, sys
from pathlib import Path
instance_id, remote_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
script = Path(remote_path).read_text(encoding="utf-8")
payload = {
    "InstanceIds": [instance_id],
    "DocumentName": "AWS-RunShellScript",
    "TimeoutSeconds": 300,
    "Comment": "LAB strip AWS keys onto instance role",
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
for _ in $(seq 1 40); do
  sleep 5
  STATUS=$(aws ssm get-command-invocation \
    --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
    --query 'Status' --output text 2>/dev/null || echo Pending)
  echo "status=$STATUS"
  if [[ "$STATUS" == "Success" || "$STATUS" == "Failed" || "$STATUS" == "Cancelled" || "$STATUS" == "TimedOut" ]]; then
    break
  fi
done

echo "=== stdout ==="
aws ssm get-command-invocation \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query 'StandardOutputContent' --output text
echo "=== stderr ==="
aws ssm get-command-invocation \
  --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
  --query 'StandardErrorContent' --output text

if [[ "$STATUS" != "Success" ]]; then
  echo "FAIL: SSM status=$STATUS" >&2
  exit 1
fi

echo ""
echo "PASS: LAB env files no longer inject static AWS keys."
echo "Do not delete IAM user jarvis-lab-bedrock until a LAB Bedrock invoke works on the instance role."
echo "Bedrock Operation not allowed is an AWS account restriction, not this IAM cutover."
