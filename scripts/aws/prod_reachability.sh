#!/usr/bin/env bash
# Diagnose PROD EC2 reachability: instance state, public IP, SSM, security group (SSH).
# No secrets required; uses existing AWS CLI configuration.
#
# Usage: ./scripts/aws/prod_reachability.sh
#   INSTANCE_ID=i-xxx REGION=ap-southeast-1 ./scripts/aws/prod_reachability.sh
#
# Answers: is instance running? does it have a public IP? is SSM online? does SG allow SSH?
# Recommends Session Manager when SSM is Online.

set -euo pipefail

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
API_BASE="${1:-https://dashboard.hilovivo.com}"

echo "=== PROD reachability (instance $INSTANCE_ID, region $REGION) ==="
echo ""

if ! command -v aws &>/dev/null; then
  echo "  AWS CLI not found. Install it to run full diagnostics."
  echo "  Public API only:"
  CODE=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 "$API_BASE/api/health" 2>/dev/null || echo "000")
  echo "  API $API_BASE/api/health: HTTP $CODE"
  exit 0
fi

# 1) Instance state and public IP (query each field so output order is stable)
STATE=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || echo "")
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || echo "")
PRIVATE_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text 2>/dev/null || echo "")
SG_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text 2>/dev/null || echo "")
[[ "$STATE" == "None" ]] && STATE=""
[[ "$PUBLIC_IP" == "None" ]] && PUBLIC_IP=""
[[ "$PRIVATE_IP" == "None" ]] && PRIVATE_IP=""
[[ "$SG_ID" == "None" ]] && SG_ID=""

if [[ -z "$STATE" || "$STATE" == "None" ]]; then
  echo "  Instance: not found or no permission (check INSTANCE_ID and AWS credentials)"
  STATE="unknown"
else
  echo "  Instance state: $STATE"
  echo "  Public IP:      ${PUBLIC_IP:-none (e.g. in private subnet or stopped)}"
  echo "  Private IP:     ${PRIVATE_IP:-n/a}"
  echo "  Security group: ${SG_ID:-n/a}"
fi
echo ""

# 2) SSM PingStatus
SSM_STATUS=""
ssm_out=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || true)
[[ -n "$ssm_out" && "$ssm_out" != "None" ]] && SSM_STATUS="$ssm_out" || SSM_STATUS="N/A (agent not registered or no permission)"

echo "  SSM PingStatus:  $SSM_STATUS"
echo ""

# 3) Does security group allow SSH (port 22)?
SSH_ALLOWED=""
if [[ -n "$SG_ID" && "$SG_ID" != "None" ]]; then
  rules=$(aws ec2 describe-security-groups --group-ids "$SG_ID" --region "$REGION" \
    --query 'SecurityGroups[0].IpPermissions[?FromPort==`22` || ToPort==`22`]' --output json 2>/dev/null || echo "[]")
  if [[ -n "$rules" && "$rules" != "[]" ]]; then
    SSH_ALLOWED="yes (SG has port 22 rule(s))"
  else
    SSH_ALLOWED="no (no port 22 in SG)"
  fi
else
  SSH_ALLOWED="n/a (no SG)"
fi
echo "  SG allows SSH:   $SSH_ALLOWED"
echo ""

# 4) Public API
CODE=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 "$API_BASE/api/health" 2>/dev/null || echo "000")
if [[ "$CODE" == "200" ]]; then
  echo "  Public API:      OK (HTTP $CODE)"
else
  echo "  Public API:      FAIL or timeout (HTTP $CODE)"
fi
echo ""

# 5) Recommendation
echo "--- Recommendation ---"
if [[ "$SSM_STATUS" == "Online" ]]; then
  echo "  Session Manager is available. Prefer SSM for deploy and shell:"
  echo "    aws ssm start-session --target $INSTANCE_ID --region $REGION"
  echo "  Deploy without SSH:"
  echo "    ./scripts/deploy_production_via_ssm.sh"
elif [[ "$STATE" == "running" && -n "$PUBLIC_IP" && "$SSH_ALLOWED" == yes* ]]; then
  echo "  SSH may work if your IP is allowed by the SG: ssh ubuntu@$PUBLIC_IP"
  echo "  If SSH times out: instance may be in a subnet without public route, or NACL/firewall blocks 22."
  echo "  Restore SSM: see docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md"
else
  echo "  SSH is unlikely (no public IP, or SG blocks 22, or instance not running)."
  echo "  If instance is running: restore SSM (runbook RUNBOOK_SSM_PROD_CONNECTION_LOST.md) then use deploy_production_via_ssm.sh"
fi
echo ""
echo "Done."
