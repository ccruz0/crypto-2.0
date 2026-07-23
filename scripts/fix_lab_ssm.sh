#!/usr/bin/env bash
# Fix LAB SSM when PingStatus is ConnectionLost (atp-lab-builder).
#
# Safe defaults:
#   - Opens SSH tcp/22 from THIS machine's public IP /32 only (never 0.0.0.0/0)
#   - Always revokes that rule on EXIT (trap), even on failure
#   - Uses EC2 Instance Connect ephemeral key (not printed); no secrets dumped
#   - Does NOT reboot by default (pass --reboot to force)
#   - Does NOT touch PROD trading stack
#
# Run from Mac with an admin AWS profile that can:
#   ec2:Authorize/RevokeSecurityGroupIngress, Describe*
#   ec2-instance-connect:SendSSHPublicKey
#   ssm:DescribeInstanceInformation
#
# Usage:
#   bash scripts/fix_lab_ssm.sh --profile YOUR_ADMIN_PROFILE
#   bash scripts/fix_lab_ssm.sh --profile YOUR_ADMIN_PROFILE --reboot
#   AWS_PROFILE=admin bash scripts/fix_lab_ssm.sh
#
set -euo pipefail

INSTANCE_ID="${LAB_INSTANCE_ID:-i-09d48ce86200848f8}"
SG_ID="${LAB_SG_ID:-sg-0b0cf3411317c5781}"
REGION="${AWS_REGION:-ap-southeast-1}"
OS_USER="${LAB_OS_USER:-ubuntu}"
PROFILE=""
DO_REBOOT=0
POLL_SECONDS="${SSM_POLL_SECONDS:-120}"
POLL_INTERVAL=10

usage() {
  sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --profile|-p) PROFILE="${2:-}"; shift 2 ;;
    --reboot) DO_REBOOT=1; shift ;;
    --instance-id) INSTANCE_ID="${2:-}"; shift 2 ;;
    --sg-id) SG_ID="${2:-}"; shift 2 ;;
    --region) REGION="${2:-}"; shift 2 ;;
    -h|--help) usage 0 ;;
    *) echo "Unknown arg: $1" >&2; usage 1 ;;
  esac
done

AWS=(aws --region "$REGION")
if [[ -n "$PROFILE" ]]; then
  AWS+=(--profile "$PROFILE")
fi

echo "=== Fix LAB SSM ==="
echo "Instance: $INSTANCE_ID"
echo "SG:       $SG_ID"
echo "Region:   $REGION"
echo "Profile:  ${PROFILE:-${AWS_PROFILE:-default}}"

# Fail fast on identity (no secrets)
echo "--- Caller ---"
"${AWS[@]}" sts get-caller-identity --query '{Account:Account,Arn:Arn}' --output json

PUBLIC_IP=$("${AWS[@]}" ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
PRIVATE_IP=$("${AWS[@]}" ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].PrivateIpAddress' --output text)
STATE=$("${AWS[@]}" ec2 describe-instances --instance-ids "$INSTANCE_ID" \
  --query 'Reservations[0].Instances[0].State.Name' --output text)

if [[ -z "$PUBLIC_IP" || "$PUBLIC_IP" == "None" ]]; then
  echo "ERROR: LAB has no public IP; Instance Connect over public SSH cannot work." >&2
  exit 1
fi
echo "State=$STATE PublicIp=$PUBLIC_IP PrivateIp=$PRIVATE_IP"

ssm_status() {
  "${AWS[@]}" ssm describe-instance-information \
    --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
    --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound"
}

STATUS="$(ssm_status)"
echo "Current SSM PingStatus: $STATUS"
if [[ "$STATUS" == "Online" ]]; then
  echo "Already Online; nothing to do."
  exit 0
fi

# Detect egress IP of THIS host (Mac / laptop)
MY_IP=$(curl -sS --max-time 8 https://checkip.amazonaws.com 2>/dev/null \
  || curl -sS --max-time 8 https://ifconfig.me/ip 2>/dev/null \
  || curl -sS --max-time 8 https://icanhazip.com 2>/dev/null \
  || true)
MY_IP="${MY_IP//[[:space:]]/}"
if [[ ! "$MY_IP" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "ERROR: could not detect this machine's public IPv4." >&2
  exit 1
fi
CIDR="${MY_IP}/32"
echo "Temporary SSH allow: $CIDR -> tcp/22 on $SG_ID"

RULE_ADDED=0
KEY_DIR=""

cleanup() {
  local ec=$?
  if [[ "$RULE_ADDED" -eq 1 ]]; then
    echo "Revoking temporary SSH rule $CIDR ..."
    "${AWS[@]}" ec2 revoke-security-group-ingress \
      --group-id "$SG_ID" \
      --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${CIDR}}]" \
      >/dev/null 2>&1 || \
    "${AWS[@]}" ec2 revoke-security-group-ingress \
      --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$CIDR" \
      >/dev/null 2>&1 || echo "WARN: revoke failed — remove $CIDR from $SG_ID manually." >&2
    RULE_ADDED=0
  fi
  if [[ -n "$KEY_DIR" && -d "$KEY_DIR" ]]; then
    rm -rf "$KEY_DIR"
  fi
  exit "$ec"
}
trap cleanup EXIT

echo "Authorizing ingress (My IP /32 only)..."
if "${AWS[@]}" ec2 authorize-security-group-ingress \
  --group-id "$SG_ID" \
  --ip-permissions "IpProtocol=tcp,FromPort=22,ToPort=22,IpRanges=[{CidrIp=${CIDR},Description=temp-fix-lab-ssm-$(date -u +%Y%m%dT%H%M%SZ)}]"; then
  RULE_ADDED=1
else
  # Idempotent: rule may already exist
  echo "authorize returned non-zero; assuming rule may already exist and continuing..."
  RULE_ADDED=1
fi

# Brief wait for SG propagation
sleep 3

if [[ "$DO_REBOOT" -eq 1 ]]; then
  echo "Rebooting LAB instance (requested)..."
  "${AWS[@]}" ec2 reboot-instances --instance-ids "$INSTANCE_ID" >/dev/null
  echo "Waiting 150s for SSH after reboot..."
  sleep 150
fi

KEY_DIR=$(mktemp -d)
ssh-keygen -t ed25519 -f "$KEY_DIR/key" -N "" -q

echo "Pushing ephemeral key via EC2 Instance Connect..."
"${AWS[@]}" ec2-instance-connect send-ssh-public-key \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user "$OS_USER" \
  --ssh-public-key "file://${KEY_DIR}/key.pub" \
  >/dev/null

SSH_OPTS=(-o ConnectTimeout=20 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$KEY_DIR/key")

echo "Restarting amazon-ssm-agent over SSH..."
ssh "${SSH_OPTS[@]}" "${OS_USER}@${PUBLIC_IP}" bash -s <<'REMOTE'
set -euo pipefail
echo "hostname=$(hostname) id=$(id -un)"
# Prefer snap unit on Ubuntu 22.04+, fall back to classic package
if systemctl list-unit-files 2>/dev/null | grep -q 'snap.amazon-ssm-agent.amazon-ssm-agent'; then
  sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service
  sudo systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent.service || true
elif systemctl list-unit-files 2>/dev/null | grep -q '^amazon-ssm-agent'; then
  sudo systemctl restart amazon-ssm-agent
  sudo systemctl is-active amazon-ssm-agent || true
else
  # Last resort: start whatever is present
  sudo systemctl restart amazon-ssm-agent 2>/dev/null || true
  sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || true
fi
# Quick health hint (no secrets)
sudo journalctl -u snap.amazon-ssm-agent.amazon-ssm-agent.service -n 15 --no-pager 2>/dev/null \
  || sudo journalctl -u amazon-ssm-agent -n 15 --no-pager 2>/dev/null \
  || true
echo "agent-restart-done"
REMOTE

echo "Polling SSM PingStatus up to ${POLL_SECONDS}s..."
deadline=$((SECONDS + POLL_SECONDS))
FINAL="NotFound"
while (( SECONDS < deadline )); do
  FINAL="$(ssm_status)"
  echo "  $(date -u +%H:%M:%S)Z  PingStatus=$FINAL"
  if [[ "$FINAL" == "Online" ]]; then
    echo "SUCCESS: SSM PingStatus=Online"
    exit 0
  fi
  sleep "$POLL_INTERVAL"
done

echo "FAILED: SSM still $FINAL after ${POLL_SECONDS}s." >&2
echo "Hints: check IAM instance profile atp-lab-builder-ssm-role, VPC endpoints / egress to SSM," >&2
echo "  and agent logs on the host. Re-run with --reboot if needed." >&2
exit 1
