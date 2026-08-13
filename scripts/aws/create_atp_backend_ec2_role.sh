#!/usr/bin/env bash
# Phase B — create atp-backend-ec2-role, attach least-privilege runtime policy,
# associate instance profile to PROD, set IMDS hop limit 2 so Docker can use the role.
#
# Does NOT edit secrets/runtime.env and does NOT restart containers (Phase C).
# Does NOT print IAM secret values or IMDS temporary credentials.
#
# Run from operator workstation (not the Cloud Agent VM):
#   AWS_PROFILE=carlos-sso ./scripts/aws/create_atp_backend_ec2_role.sh
#
# Requires: iam:CreateRole, iam:PutRolePolicy, iam:AttachRolePolicy,
# iam:CreateInstanceProfile, iam:AddRoleToInstanceProfile,
# ec2:DescribeIamInstanceProfileAssociations,
# ec2:AssociateIamInstanceProfile / ReplaceIamInstanceProfileAssociation,
# ec2:ModifyInstanceMetadataOptions, ssm:SendCommand (for IMDS verify).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
REGION="${AWS_REGION:-ap-southeast-1}"
export AWS_PROFILE="${AWS_PROFILE:-carlos-sso}"
export AWS_DEFAULT_REGION="$REGION"

ROLE_NAME="atp-backend-ec2-role"
PROFILE_NAME="atp-backend-ec2-profile"
INLINE_POLICY_NAME="atp-backend-runtime"
INSTANCE_ID="i-087953603011543c5"
EXISTING_ROLE="EC2_SSM_Role"
TRUST_FILE="$ROOT/ci-cd/iam/trust-atp-backend-ec2.json"
POLICY_FILE="$ROOT/ci-cd/iam/policy-atp-backend-runtime.json"

if [[ ! -f "$TRUST_FILE" || ! -f "$POLICY_FILE" ]]; then
  echo "FAIL: missing $TRUST_FILE or $POLICY_FILE" >&2
  exit 1
fi

echo "=== Phase B: instance role for PROD $INSTANCE_ID ==="
echo "Profile: $AWS_PROFILE  Region: $REGION"
echo ""

if ! ID_JSON=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "FAIL: cannot assume AWS_PROFILE=$AWS_PROFILE. On the Mac: aws sso login --profile carlos-sso" >&2
  exit 1
fi
echo "Caller: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Arn'])" "$ID_JSON")"
echo "Account: $(python3 -c "import json,sys; print(json.loads(sys.argv[1])['Account'])" "$ID_JSON")"
echo ""

echo "=== Current instance profile on PROD ==="
ASSOC_JSON=$(aws ec2 describe-iam-instance-profile-associations \
  --filters "Name=instance-id,Values=$INSTANCE_ID" \
  --region "$REGION" --output json)
python3 - <<'PY' "$ASSOC_JSON"
import json, sys
data = json.loads(sys.argv[1])
assocs = data.get("IamInstanceProfileAssociations") or []
if not assocs:
    print("none attached")
    raise SystemExit(0)
for a in assocs:
    prof = a.get("IamInstanceProfile") or {}
    print(f"association_id={a.get('AssociationId')} state={a.get('State')} arn={prof.get('Arn')} id={prof.get('Id')}")
PY
echo ""

echo "=== Existing $EXISTING_ROLE (dump names so we do not drop SSM/ECR) ==="
if aws iam get-role --role-name "$EXISTING_ROLE" >/dev/null 2>&1; then
  echo "managed:"
  aws iam list-attached-role-policies --role-name "$EXISTING_ROLE" \
    --query 'AttachedPolicies[].{Name:PolicyName,Arn:PolicyArn}' --output table || true
  echo "inline:"
  aws iam list-role-policies --role-name "$EXISTING_ROLE" \
    --query 'PolicyNames' --output table || true
else
  echo "(role $EXISTING_ROLE not found — continue)"
fi
echo ""

echo "=== Create role $ROLE_NAME ==="
if aws iam get-role --role-name "$ROLE_NAME" >/dev/null 2>&1; then
  echo "role exists"
else
  aws iam create-role \
    --role-name "$ROLE_NAME" \
    --assume-role-policy-document "file://$TRUST_FILE" \
    --description "ATP PROD EC2 instance role: SSM + ECR pull + Jarvis/backend runtime (no static keys)"
  echo "created $ROLE_NAME"
fi

echo "=== Attach AmazonSSMManagedInstanceCore ==="
if aws iam list-attached-role-policies --role-name "$ROLE_NAME" \
  --query 'AttachedPolicies[].PolicyArn' --output text | grep -q 'AmazonSSMManagedInstanceCore'; then
  echo "already attached"
else
  aws iam attach-role-policy \
    --role-name "$ROLE_NAME" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  echo "attached"
fi

echo "=== Put inline policy $INLINE_POLICY_NAME ==="
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name "$INLINE_POLICY_NAME" \
  --policy-document "file://$POLICY_FILE"
echo "ok"

echo "=== Instance profile $PROFILE_NAME ==="
if aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" >/dev/null 2>&1; then
  echo "profile exists"
else
  aws iam create-instance-profile --instance-profile-name "$PROFILE_NAME"
  echo "created $PROFILE_NAME"
fi

ROLES_IN_PROFILE=$(aws iam get-instance-profile --instance-profile-name "$PROFILE_NAME" \
  --query 'InstanceProfile.Roles[].RoleName' --output text)
if echo " $ROLES_IN_PROFILE " | grep -q " $ROLE_NAME "; then
  echo "role already in profile"
else
  aws iam add-role-to-instance-profile \
    --instance-profile-name "$PROFILE_NAME" \
    --role-name "$ROLE_NAME"
  echo "added $ROLE_NAME to $PROFILE_NAME"
  echo "waiting 10s for instance-profile propagation..."
  sleep 10
fi

echo "=== IMDS hop limit 2 (required for Docker to reach the role) ==="
aws ec2 modify-instance-metadata-options \
  --instance-id "$INSTANCE_ID" \
  --http-tokens required \
  --http-put-response-hop-limit 2 \
  --http-endpoint enabled \
  --region "$REGION"
echo "ok"

echo "=== Associate profile to PROD (no instance reboot) ==="
ASSOC_ID=$(aws ec2 describe-iam-instance-profile-associations \
  --filters "Name=instance-id,Values=$INSTANCE_ID" \
  --region "$REGION" \
  --query 'IamInstanceProfileAssociations[0].AssociationId' \
  --output text)
CURRENT_ARN=$(aws ec2 describe-iam-instance-profile-associations \
  --filters "Name=instance-id,Values=$INSTANCE_ID" \
  --region "$REGION" \
  --query 'IamInstanceProfileAssociations[0].IamInstanceProfile.Arn' \
  --output text)

if [[ -z "$ASSOC_ID" || "$ASSOC_ID" == "None" ]]; then
  aws ec2 associate-iam-instance-profile \
    --instance-id "$INSTANCE_ID" \
    --iam-instance-profile "Name=$PROFILE_NAME" \
    --region "$REGION"
  echo "associated $PROFILE_NAME"
else
  echo "current profile arn: $CURRENT_ARN"
  if echo "$CURRENT_ARN" | grep -q "$PROFILE_NAME"; then
    echo "already associated with $PROFILE_NAME"
  else
    aws ec2 replace-iam-instance-profile-association \
      --association-id "$ASSOC_ID" \
      --iam-instance-profile "Name=$PROFILE_NAME" \
      --region "$REGION"
    echo "replaced association $ASSOC_ID -> $PROFILE_NAME"
  fi
fi

echo ""
echo "=== Verify IMDS role name via SSM (host, not container) ==="
echo "Waiting 20s for SSM agent to refresh credentials..."
sleep 20

INPUT_FILE="$(mktemp)"
python3 - "$INSTANCE_ID" "$INPUT_FILE" <<'PY'
import json, sys
instance_id, path = sys.argv[1], sys.argv[2]
payload = {
    "InstanceIds": [instance_id],
    "DocumentName": "AWS-RunShellScript",
    "TimeoutSeconds": 30,
    "Parameters": {
        "commands": [
            'TOKEN=$(curl -sS -m 3 -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")',
            'curl -sS -m 3 -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/',
            "echo",
        ]
    },
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(payload, fh)
PY
trap 'rm -f "$INPUT_FILE"' EXIT

VERIFY_OK=0
for attempt in 1 2 3 4 5 6; do
  CMD_ID=$(aws ssm send-command \
    --cli-input-json "file://$INPUT_FILE" \
    --region "$REGION" \
    --query 'Command.CommandId' --output text 2>/dev/null || true)
  if [[ -z "$CMD_ID" || "$CMD_ID" == "None" ]]; then
    echo "SSM send-command failed (attempt $attempt). Retry in 15s..."
    sleep 15
    continue
  fi
  for _ in 1 2 3 4 5 6 7 8; do
    sleep 3
    STATUS=$(aws ssm get-command-invocation \
      --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
      --query 'Status' --output text 2>/dev/null || echo Pending)
    if [[ "$STATUS" == "Success" || "$STATUS" == "Failed" || "$STATUS" == "Cancelled" || "$STATUS" == "TimedOut" ]]; then
      break
    fi
  done
  OUT=$(aws ssm get-command-invocation \
    --command-id "$CMD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" \
    --query 'StandardOutputContent' --output text 2>/dev/null || true)
  ROLE_SEEN=$(echo "$OUT" | tr -d '\r' | awk 'NF{print; exit}')
  echo "IMDS role name: ${ROLE_SEEN:-<empty>}  (ssm status=$STATUS)"
  if [[ "$ROLE_SEEN" == "$ROLE_NAME" ]]; then
    VERIFY_OK=1
    break
  fi
  echo "not yet $ROLE_NAME; retry..."
  sleep 15
done

echo ""
if [[ "$VERIFY_OK" -eq 1 ]]; then
  echo "PASS: host IMDS shows $ROLE_NAME"
  echo "Phase B done. Do not restart containers yet. Next: Phase C (remove AWS_ACCESS_KEY_* lines from runtime.env)."
  echo "If Docker still cannot assume the role after Phase C, hop limit is already 2."
else
  echo "WARN: SSM did not confirm IMDS role name yet (agent may still be refreshing)."
  echo "From ssh prod (prints ROLE NAME only — do not curl the role path under security-credentials/):"
  echo '  TOKEN=$(curl -sS -X PUT "http://169.254.169.254/latest/api/token" -H "X-aws-ec2-metadata-token-ttl-seconds: 60")'
  echo '  curl -sS -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/iam/security-credentials/'
  echo "Expected output: $ROLE_NAME"
  exit 2
fi
