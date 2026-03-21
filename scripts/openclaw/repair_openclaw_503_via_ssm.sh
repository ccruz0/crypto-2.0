#!/usr/bin/env bash
# Fix OpenClaw 503/504 without SSH from your Mac (uses SSM Run Command).
# Use when: repair_openclaw_503.sh / fix_504_via_eice.sh fail with "Permission denied (publickey)"
# — SG often blocks :22 from home; Instance Connect can still fail; SSM uses the agent on the instance.
#
# Requires: AWS CLI, ssm:SendCommand on these instances, SSM agent Online.
#
# Env (optional):
#   ATP_INSTANCE_ID / DASHBOARD_INSTANCE_ID  (default i-087953603011543c5)
#   OPENCLAW_LAB_INSTANCE_ID / LAB_INSTANCE_ID (default i-0d82c172235770a0d)
#   AWS_REGION (default ap-southeast-1)
#   ATP_REPO_PATH (default /home/ubuntu/automated-trading-platform)
#
set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
DASHBOARD_INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-${ATP_INSTANCE_ID:-i-087953603011543c5}}"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-${OPENCLAW_LAB_INSTANCE_ID:-i-0d82c172235770a0d}}"
REPO="${ATP_REPO_PATH:-/home/ubuntu/automated-trading-platform}"
LAB_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
PORT="${OPENCLAW_PORT:-8080}"

check_ssm() {
  aws ssm describe-instance-information --region "$AWS_REGION" \
    --filters "Key=InstanceIds,Values=$1" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound"
}

wait_ssm() {
  local cmd_id="$1" iid="$2" max="${3:-60}"
  local status="Pending"
  local i=0
  while [[ "$i" -lt "$max" ]]; do
    status=$(aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$iid" \
      --region "$AWS_REGION" \
      --query "Status" --output text 2>/dev/null || echo "Pending")
    [[ "$status" == "Success" || "$status" == "Failed" || "$status" == "Cancelled" ]] && break
    sleep 2
    i=$((i + 1))
  done
  echo "Status: $status" >&2
  aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$iid" \
    --region "$AWS_REGION" \
    --query '[StandardOutputContent,StandardErrorContent]' \
    --output text 2>/dev/null || true
}

echo "=== OpenClaw repair via SSM (no laptop SSH) ==="
echo "Dashboard: $DASHBOARD_INSTANCE_ID  LAB: $LAB_INSTANCE_ID  region: $AWS_REGION"
echo ""

for id in "$DASHBOARD_INSTANCE_ID" "$LAB_INSTANCE_ID"; do
  st=$(check_ssm "$id")
  echo "SSM PingStatus $id: $st"
  if [[ "$st" != "Online" ]]; then
    echo "ERROR: SSM not Online for $id. Fix agent/IAM/endpoint (see docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md)."
    exit 1
  fi
done
echo ""

# --- Dashboard: pull + deploy nginx + force upstream + reload ---
echo "=== 1/2 Dashboard: git pull + deploy_openclaw_basepath_nginx + reload nginx ==="
# shellcheck disable=SC2016
DASH_PARAMS=$(cat <<EOF
{
  "commands": [
    "set -e",
    "sudo systemctl start nginx 2>/dev/null || true",
    "sudo -u ubuntu bash -lc 'cd $REPO && git fetch origin main && git checkout main && git pull origin main'",
    "sudo -u ubuntu bash -lc 'cd $REPO && bash scripts/openclaw/deploy_openclaw_basepath_nginx.sh'",
    "sudo bash -lc 'export LAB_PRIVATE_IP=$LAB_IP; export OPENCLAW_PORT=$PORT; bash $REPO/scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh || true'",
    "sudo nginx -t",
    "sudo systemctl reload nginx",
    "echo --- curl public /openclaw/ ---",
    "curl -sS -m 12 -I https://dashboard.hilovivo.com/openclaw/ | head -15 || true",
    "echo --- curl LAB upstream from dashboard ---",
    "curl -sS -m 5 -I http://$LAB_IP:$PORT/ | head -8 || true"
  ]
}
EOF
)

DASH_CMD=$(aws ssm send-command \
  --instance-ids "$DASHBOARD_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "$DASH_PARAMS" \
  --region "$AWS_REGION" \
  --timeout-seconds 300 \
  --output text \
  --query "Command.CommandId")

wait_ssm "$DASH_CMD" "$DASHBOARD_INSTANCE_ID" 90
echo ""

# --- LAB: pull + compose up (no full rebuild) ---
echo "=== 2/2 LAB: git pull + docker compose openclaw up -d ==="
LAB_PARAMS=$(cat <<EOF
{
  "commands": [
    "set -e",
    "sudo mkdir -p $REPO/secrets /opt/openclaw/home-data 2>/dev/null || true",
    "sudo chown -R ubuntu:ubuntu $REPO /opt/openclaw 2>/dev/null || true",
    "sudo -u ubuntu bash -lc 'cd $REPO && git fetch origin main && git checkout main && git pull origin main'",
    "sudo -u ubuntu bash -lc 'mkdir -p $REPO/secrets && touch $REPO/secrets/runtime.env'",
    "sudo -u ubuntu bash -lc 'cd $REPO && (sg docker -c \"docker compose -f docker-compose.openclaw.yml up -d\" || docker compose -f docker-compose.openclaw.yml up -d)'",
    "sleep 4",
    "sudo ss -lntp | grep -E ':8080|:18789' || true",
    "curl -sS -m 5 -I http://127.0.0.1:8080/ | head -8 || true"
  ]
}
EOF
)

LAB_CMD=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters "$LAB_PARAMS" \
  --region "$AWS_REGION" \
  --timeout-seconds 300 \
  --output text \
  --query "Command.CommandId")

wait_ssm "$LAB_CMD" "$LAB_INSTANCE_ID" 120
echo ""
echo "=== Done ==="
echo "Browser: https://dashboard.hilovivo.com/openclaw/ (expect 401; after login, not 503)."
echo "If LAB curl from dashboard still fails: open LAB security group TCP $PORT from dashboard private IP."
