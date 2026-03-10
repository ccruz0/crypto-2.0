#!/usr/bin/env bash
# Run the 504 runbook's 3 commands via SSM (Dashboard + OpenClaw/LAB).
# Usage: ./scripts/openclaw/run_504_diagnosis_ssm.sh
# Requires: AWS CLI, SSM access to Dashboard and LAB instances.
# If Dashboard shows ConnectionLost: run the 3 commands manually (SSH or fix SSM first).
# See: docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md

set -e
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
DASHBOARD_INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-i-087953603011543c5}"   # atp-rebuild-2026, 52.220.32.147
OPENCLAW_INSTANCE_ID="${OPENCLAW_INSTANCE_ID:-i-0d82c172235770a0d}"   # atp-lab-ssm-clean (LAB)

# Pre-check SSM status so we fail fast with a clear message
check_ssm() {
  local status
  status=$(aws ssm describe-instance-information --region "$AWS_REGION" \
    --filters "Key=InstanceIds,Values=$1" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
  echo "$status"
}

run_ssm() {
  local instance_id="$1"
  local params="$2"
  local cmd_id
  cmd_id=$(aws ssm send-command \
    --instance-ids "$instance_id" \
    --document-name "AWS-RunShellScript" \
    --parameters "$params" \
    --region "$AWS_REGION" \
    --output text \
    --query "Command.CommandId" 2>/dev/null) || { echo "Failed to send command to $instance_id" >&2; return 1; }
  echo "$cmd_id"
}

get_ssm_output() {
  local cmd_id="$1"
  local instance_id="$2"
  local max_wait=15
  local status=""
  for i in $(seq 1 "$max_wait"); do
    status=$(aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$instance_id" \
      --region "$AWS_REGION" \
      --query "Status" \
      --output text 2>/dev/null || echo "NotFound")
    [[ "$status" == "Success" || "$status" == "Failed" || "$status" == "Cancelled" ]] && break
    sleep 1
  done
  echo "Status: $status" >&2
  if [[ "$status" == "Failed" ]]; then
    aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$instance_id" \
      --region "$AWS_REGION" \
      --query "StandardErrorContent" \
      --output text 2>/dev/null || true
  fi
  aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$instance_id" \
    --region "$AWS_REGION" \
    --query "StandardOutputContent" \
    --output text 2>/dev/null || echo "(no output)"
}

echo "=== 504 runbook: 3 outputs via SSM ==="
DASH_STATUS=$(check_ssm "$DASHBOARD_INSTANCE_ID")
OC_STATUS=$(check_ssm "$OPENCLAW_INSTANCE_ID")
echo "Dashboard ($DASHBOARD_INSTANCE_ID): SSM $DASH_STATUS"
echo "OpenClaw ($OPENCLAW_INSTANCE_ID): SSM $OC_STATUS"
if [[ "$DASH_STATUS" != "Online" ]]; then
  echo ""
  echo "Dashboard SSM is not Online. Run the 3 commands manually on 52.220.32.147 (SSH) and on the OpenClaw host."
  echo "See docs/openclaw/OPENCLAW_504_UPSTREAM_DIAGNOSIS.md — Quick copy-paste section."
  echo "To fix SSM on PROD: docs/aws/RUNBOOK_SSM_PROD_CONNECTION_LOST.md"
  exit 1
fi
echo ""

# --- 1) Dashboard: Nginx openclaw location (proxy_pass)
echo "--- 1) Dashboard: Nginx location ^~ /openclaw/ (proxy_pass) ---"
CMD1_PARAMS='{"commands":["sudo nginx -T 2>/dev/null | sed -n '\''/server_name dashboard.hilovivo.com/,/^}/p'\'' | sed -n '\''/location \\^~ \\/openclaw\\//,/}/p'\''"]}'
CMD1=$(run_ssm "$DASHBOARD_INSTANCE_ID" "$CMD1_PARAMS")
OUT1=$(get_ssm_output "$CMD1" "$DASHBOARD_INSTANCE_ID")
echo "$OUT1"
echo ""

# Extract upstream IP for step 2
UPSTREAM_IP=$(echo "$OUT1" | grep -oE 'proxy_pass http://[0-9.]+:8080' | sed 's|proxy_pass http://||;s|:8080||' | head -1)
if [ -z "$UPSTREAM_IP" ]; then
  UPSTREAM_IP=""
fi
echo "(parsed proxy_pass upstream: ${UPSTREAM_IP:-<none>})"
echo ""

# --- 2) Dashboard: curl to upstream
echo "--- 2) Dashboard: curl to upstream (max-time 3) ---"
if [ -n "$UPSTREAM_IP" ]; then
  CMD2_PARAMS=$(printf '{"commands":["curl -sv --max-time 3 http://%s:8080/ 2>&1 || true"]}' "$UPSTREAM_IP")
  CMD2=$(run_ssm "$DASHBOARD_INSTANCE_ID" "$CMD2_PARAMS")
  OUT2=$(get_ssm_output "$CMD2" "$DASHBOARD_INSTANCE_ID")
  echo "$OUT2"
else
  echo "Skipped (no IP from step 1). Run manually on Dashboard: curl -sv --max-time 3 http://<IP>:8080/"
fi
echo ""

# --- 3) OpenClaw host: ss :8080
echo "--- 3) OpenClaw host: ss -lntp | grep ':8080' ---"
CMD3_PARAMS='{"commands":["sudo ss -lntp | grep '\'':8080'\'' || true"]}'
CMD3=$(run_ssm "$OPENCLAW_INSTANCE_ID" "$CMD3_PARAMS")
OUT3=$(get_ssm_output "$CMD3" "$OPENCLAW_INSTANCE_ID")
echo "$OUT3"
echo ""

echo "=== End of 3 outputs. Use runbook table to pick the single fix. ==="
