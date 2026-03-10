#!/usr/bin/env bash
# Bring dashboard.hilovivo.com back when browser shows ERR_TIMED_OUT.
# Uses AWS CLI to start PROD if stopped, optionally reboot if running but dead,
# checks DNS vs current public IP, then curls health.
#
# Usage:
#   ./scripts/aws/bringup_dashboard_prod.sh
#   AUTO_START=1 ./scripts/aws/bringup_dashboard_prod.sh    # start instance without prompt
#   AUTO_REBOOT=1 ./scripts/aws/bringup_dashboard_prod.sh   # if Running but curl fails, reboot
#
# Requires: aws cli configured, permissions ec2:DescribeInstances, ec2:StartInstances, ec2:RebootInstances
# PROD: atp-rebuild-2026 i-087953603011543c5

set -euo pipefail

INSTANCE_ID="${DASHBOARD_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
DOMAIN="${DASHBOARD_DOMAIN:-dashboard.hilovivo.com}"
AUTO_START="${AUTO_START:-}"
AUTO_REBOOT="${AUTO_REBOOT:-}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"

log() { echo "[bringup] $*"; }

need_aws() {
  command -v aws >/dev/null 2>&1 || { log "ERROR: AWS CLI not found."; exit 1; }
}

instance_state_and_ip() {
  # Output: STATE<TAB>PUBLIC_IP (explicit order via json)
  aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
    --query 'Reservations[0].Instances[0].[State.Name,PublicIpAddress]' --output text 2>/dev/null | tr '\t' ' ' || echo "unknown "
}

dns_a() {
  dig +short "$DOMAIN" A 2>/dev/null | head -1 || true
}

wait_running() {
  local max=60
  local n=0
  while [ "$n" -lt "$max" ]; do
    read -r state ip _ <<< "$(instance_state_and_ip)"
    if [ "$state" = "running" ] && [ -n "$ip" ] && [ "$ip" != "None" ]; then
      echo "$ip"
      return 0
    fi
    sleep 5
    n=$((n + 5))
    log "waiting for running... ($n s)"
  done
  return 1
}

log "PROD instance $INSTANCE_ID region $REGION"

need_aws
read -r STATE PUBLIC_IP <<< "$(instance_state_and_ip)"
# Normalize: aws returns "None" for no public IP
[ "$PUBLIC_IP" = "None" ] && PUBLIC_IP=""
log "State=$STATE PublicIp=${PUBLIC_IP:-<none>}"

if [ "$STATE" = "stopped" ] || [ "$STATE" = "stopping" ]; then
  log "Instance is not running — dashboard will time out until it starts."
  if [ -z "$AUTO_START" ]; then
    read -r -p "Start instance now? [y/N] " ans
    [[ "${ans:-}" =~ ^[Yy]$ ]] || { log "Aborted. Start manually: aws ec2 start-instances --region $REGION --instance-ids $INSTANCE_ID"; exit 1; }
  fi
  aws ec2 start-instances --region "$REGION" --instance-ids "$INSTANCE_ID"
  log "Start issued. Waiting for running + public IP..."
  PUBLIC_IP=$(wait_running) || { log "Timeout waiting for running."; exit 1; }
  log "Running. Public IP: $PUBLIC_IP"
fi

if [ "$STATE" = "running" ]; then
  if [ -z "${PUBLIC_IP:-}" ] || [ "${PUBLIC_IP:-}" = "None" ]; then
    PUBLIC_IP=$(aws ec2 describe-instances --region "$REGION" --instance-ids "$INSTANCE_ID" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text 2>/dev/null || true)
  fi
fi

DNS_IP=$(dns_a)
if [ -n "$PUBLIC_IP" ] && [ "$PUBLIC_IP" != "None" ] && [ -n "$DNS_IP" ] && [ "$DNS_IP" != "$PUBLIC_IP" ]; then
  log "WARNING: DNS $DOMAIN -> $DNS_IP but instance Public IP is $PUBLIC_IP"
  log "Update DNS A record to $PUBLIC_IP or attach Elastic IP — see docs/runbooks/DASHBOARD_UNREACHABLE_RUNBOOK.md"
fi

# Curl health via domain (what browser uses)
if bash "$REPO_ROOT/scripts/aws/verify_prod_public.sh" "https://$DOMAIN" 2>/dev/null; then
  log "Dashboard reachable. Done."
  exit 0
fi

log "HTTPS still failing. If instance is Running, try reboot (SSM agent / nginx stack)."
RUNNING_NOW="$STATE"
[ -z "$RUNNING_NOW" ] && read -r RUNNING_NOW _ <<< "$(instance_state_and_ip)"
if [ "$RUNNING_NOW" = "running" ] || [ "$STATE" = "running" ]; then
  if [ -n "$AUTO_REBOOT" ]; then
    log "Rebooting $INSTANCE_ID..."
    aws ec2 reboot-instances --region "$REGION" --instance-ids "$INSTANCE_ID"
    log "Reboot issued. Wait 3–5 min then re-run: ./scripts/aws/verify_prod_public.sh"
  else
    log "Optional: AUTO_REBOOT=1 $0  or  aws ec2 reboot-instances --region $REGION --instance-ids $INSTANCE_ID"
    log "Or EC2 Console → Instance state → Reboot."
  fi
fi

log "If still timing out from home, try mobile hotspot (network path) — same runbook."
exit 1
