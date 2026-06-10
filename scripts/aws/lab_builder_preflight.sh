#!/usr/bin/env bash
# Read-only Phase 2A.0 preflight for atp-lab-builder bootstrap.
# Run from an operator workstation with admin IAM (NOT from PROD instance role alone).
# See: docs/runbooks/LAB_JARVIS_BUILDER_BOOTSTRAP.md
set -euo pipefail

REGION="${AWS_REGION:-ap-southeast-1}"
VPC_ID="${ATP_VPC_ID:-vpc-09930b85e52722581}"
SUBNET_ID="${ATP_LAB_SUBNET:-subnet-055b8b41048d648aa}"
BUILDER_SG_NAME="${ATP_LAB_BUILDER_SG:-atp-lab-builder-sg}"
BUILDER_ROLE="${ATP_LAB_BUILDER_ROLE:-atp-lab-builder-ssm-role}"

PASS=0
FAIL=0
WARN=0

ok()   { echo "  PASS  $*"; PASS=$((PASS + 1)); }
fail() { echo "  FAIL  $*"; FAIL=$((FAIL + 1)); }
warn() { echo "  WARN  $*"; WARN=$((WARN + 1)); }

echo "=== ATP Lab Builder Preflight (read-only) ==="
echo "Region: $REGION  VPC: $VPC_ID  Subnet: $SUBNET_ID"
echo ""

echo "--- 1) Caller identity ---"
if ID=$(aws sts get-caller-identity --output json 2>/dev/null); then
  echo "$ID"
  ok "sts get-caller-identity"
else
  fail "sts get-caller-identity (no AWS credentials?)"
fi
echo ""

echo "--- 2) Subnet ---"
if SUB=$(aws ec2 describe-subnets --region "$REGION" --subnet-ids "$SUBNET_ID" --output json 2>/dev/null); then
  AZ=$(echo "$SUB" | python3 -c "import sys,json; s=json.load(sys.stdin)['Subnets'][0]; print(s['AvailabilityZone'], s['CidrBlock'], s['VpcId'])")
  echo "  $SUBNET_ID → $AZ"
  if echo "$SUB" | grep -q "$VPC_ID"; then ok "subnet in target VPC"; else fail "subnet not in $VPC_ID"; fi
else
  fail "ec2:DescribeSubnets denied or subnet missing — admin IAM required"
fi
echo ""

echo "--- 3) Security groups ---"
if aws ec2 describe-security-groups --region "$REGION" --group-names "$BUILDER_SG_NAME" >/dev/null 2>&1; then
  warn "$BUILDER_SG_NAME already exists (reuse or delete before create)"
else
  ok "$BUILDER_SG_NAME absent (ready to create)"
fi
if SG2=$(aws ec2 describe-security-groups --region "$REGION" --group-names atp-lab-sg2 --query 'SecurityGroups[0].IpPermissions' --output json 2>/dev/null); then
  if echo "$SG2" | grep -q '0.0.0.0/0'; then
    warn "atp-lab-sg2 has 0.0.0.0/0 inbound — do NOT reuse for builder"
  fi
fi
echo ""

echo "--- 4) IAM role / instance profile ---"
for NAME in "$BUILDER_ROLE" atp-lab-ssm-role EC2_SSM_Role; do
  if aws iam get-role --role-name "$NAME" >/dev/null 2>&1; then
    echo "  role exists: $NAME"
    POL=$(aws iam list-attached-role-policies --role-name "$NAME" --query 'AttachedPolicies[*].PolicyName' --output text 2>/dev/null || true)
    INLINE=$(aws iam list-role-policies --role-name "$NAME" --query 'PolicyNames' --output text 2>/dev/null || true)
    echo "    attached: ${POL:-none}  inline: ${INLINE:-none}"
    if [[ "$NAME" == "$BUILDER_ROLE" ]]; then
      if echo "$POL $INLINE" | grep -qi ssm; then ok "$NAME has SSM policy"; else warn "$NAME missing SSM managed policy"; fi
      if echo "$INLINE" | grep -qi bedrock; then ok "$NAME has bedrock inline policy"; else warn "$NAME missing bedrock invoke inline policy"; fi
    fi
  else
    [[ "$NAME" == "$BUILDER_ROLE" ]] && ok "$NAME absent (ready to create)" || echo "  role absent: $NAME"
  fi
done
echo ""

echo "--- 5) Existing instances (lab/builder/staging tags) ---"
INST=$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:Name,Values=*lab*,*builder*,*staging*,*openclaw*" \
  --query 'Reservations[*].Instances[*].[InstanceId,Tags[?Key==`Name`].Value|[0],State.Name]' \
  --output text 2>/dev/null || true)
if [[ -n "${INST:-}" ]]; then
  echo "$INST" | while read -r line; do warn "tagged instance: $line"; done
else
  ok "no lab/builder/staging/openclaw tagged instances found"
fi
echo ""

echo "--- 6) SSM managed instances ---"
aws ssm describe-instance-information --region "$REGION" \
  --query 'InstanceInformationList[*].{Id:InstanceId,Status:PingStatus,Platform:PlatformName}' \
  --output table 2>/dev/null || warn "ssm:DescribeInstanceInformation failed"
echo ""

echo "--- 7) Bedrock (us-east-1 + $REGION) ---"
for R in us-east-1 "$REGION"; do
  if N=$(aws bedrock list-foundation-models --region "$R" --query 'length(modelSummaries)' --output text 2>/dev/null); then
    ok "bedrock list models in $R ($N models)"
  else
    fail "bedrock list models in $R (enable model access / IAM bedrock:ListFoundationModels)"
  fi
done
echo ""

echo "--- 8) LAB SSM parameters (GitHub App) ---"
for P in \
  /automated-trading-platform/lab/github_app/app_id \
  /automated-trading-platform/lab/github_app/installation_id \
  /automated-trading-platform/lab/github_app/private_key_b64; do
  if aws ssm get-parameter --region "$REGION" --name "$P" >/dev/null 2>&1; then
    ok "SSM $P present"
  else
    warn "SSM $P missing (Builder PR flow needs LAB GitHub App or manual env)"
  fi
done
echo ""

echo "--- 9) Compose lab profile (local syntax) ---"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
if docker compose -f "$REPO_ROOT/docker-compose.yml" -f "$REPO_ROOT/docker-compose.lab.yml" --profile lab config >/dev/null 2>&1; then
  ok "docker compose lab profile config valid"
else
  ERR=$(docker compose -f "$REPO_ROOT/docker-compose.yml" -f "$REPO_ROOT/docker-compose.lab.yml" --profile lab config 2>&1 || true)
  if echo "$ERR" | grep -q 'secrets/runtime.env.*permission denied'; then
    warn "compose config skipped (secrets/runtime.env not readable here — OK on builder host)"
  else
    fail "docker compose lab profile config invalid: $(echo "$ERR" | tail -1)"
  fi
fi
echo ""

echo "=== Summary: PASS=$PASS  WARN=$WARN  FAIL=$FAIL ==="
if [[ "$FAIL" -gt 0 ]]; then
  echo "Verdict: NO-GO — fix FAIL items before creating AWS resources."
  exit 1
fi
if [[ "$WARN" -gt 0 ]]; then
  echo "Verdict: CONDITIONAL GO — review WARN items."
  exit 0
fi
echo "Verdict: GO — proceed with LAB_JARVIS_BUILDER_BOOTSTRAP.md Phases 1–3."
exit 0
