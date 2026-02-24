#!/usr/bin/env bash
# One-shot PROD + LAB status: public API and SSM.
# Usage: ./scripts/aws/prod_status.sh [API_BASE_URL]
# Requires: curl. Optional: AWS CLI (for SSM status).

set -e
API_BASE="${1:-https://dashboard.hilovivo.com}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "=== PROD/LAB status ==="
echo ""

# 1) Public API
HEALTH_URL="${API_BASE%/}/api/health"
CODE=$(curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 10 "$HEALTH_URL" 2>/dev/null || echo "000")
if [ "$CODE" = "200" ]; then
  echo "  PROD API ($HEALTH_URL): OK (HTTP $CODE)"
  API_OK=1
else
  echo "  PROD API ($HEALTH_URL): FAIL (HTTP $CODE)"
  API_OK=0
fi

echo ""

# 2) SSM (if AWS CLI available)
if command -v aws &>/dev/null; then
  for id in i-087953603011543c5 i-0d82c172235770a0d; do
    name="$id"
    [ "$id" = "i-087953603011543c5" ] && name="atp-rebuild-2026 (PROD)"
    [ "$id" = "i-0d82c172235770a0d" ] && name="atp-lab-ssm-clean (LAB)"
    status=$(aws ssm describe-instance-information --region "$REGION" \
      --filters "Key=InstanceIds,Values=$id" \
      --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "N/A")
    echo "  SSM $name: $status"
  done
else
  echo "  SSM: (install AWS CLI to see status)"
fi

echo ""
if [ "$API_OK" = "1" ]; then
  echo "Summary: PROD API reachable."
  exit 0
else
  echo "Summary: PROD API not reachable."
  exit 1
fi
