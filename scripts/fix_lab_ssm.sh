#!/usr/bin/env bash
# Fix LAB SSM when PingStatus is ConnectionLost (atp-lab-builder).
#
# Safe defaults:
#   - Opens SSH tcp/22 from THIS machine's public IP /32 only (never 0.0.0.0/0)
#   - Always revokes that rule on EXIT (trap), even on failure
#   - Uses EC2 Instance Connect ephemeral key (not printed); no secrets dumped
#   - Does NOT reboot by default (pass --reboot to force)
#   - Does NOT touch PROD trading stack
#   - After SSH: frees root disk (logs/cache/docker) so SSM can write again
#
# Run from Mac with an admin AWS profile that can:
#   ec2:Authorize/RevokeSecurityGroupIngress, Describe*
#   ec2-instance-connect:SendSSHPublicKey
#   ssm:DescribeInstanceInformation
#
# Usage:
#   bash scripts/fix_lab_ssm.sh
#   bash scripts/fix_lab_ssm.sh --profile YOUR_ADMIN_PROFILE
#   bash scripts/fix_lab_ssm.sh --reboot
#   AWS_PROFILE=admin bash scripts/fix_lab_ssm.sh
#
set -euo pipefail

INSTANCE_ID="${LAB_INSTANCE_ID:-i-09d48ce86200848f8}"
SG_ID="${LAB_SG_ID:-sg-0b0cf3411317c5781}"
REGION="${AWS_REGION:-ap-southeast-1}"
OS_USER="${LAB_OS_USER:-ubuntu}"
PROFILE=""
DO_REBOOT=0
# Agent often needs several minutes after disk reclaim + restart
POLL_SECONDS="${SSM_POLL_SECONDS:-240}"
POLL_INTERVAL=10

usage() {
  sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'
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

# EIC keys expire ~60s; re-push before long remote work if needed
echo "Disk cleanup + restart amazon-ssm-agent over SSH..."
ssh "${SSH_OPTS[@]}" "${OS_USER}@${PUBLIC_IP}" bash -s <<'REMOTE'
set -euo pipefail
echo "hostname=$(hostname) id=$(id -un)"
echo "=== df BEFORE cleanup ==="
df -h / || true
df -i / || true

# Guard: never touch crypto-2.0 tree or user project data
PROTECTED="/home/ubuntu/crypto-2.0"
if [[ -e "$PROTECTED" ]]; then
  echo "Protected path present (will not delete): $PROTECTED"
fi

echo "--- journal vacuum (to 100M / 2d) ---"
sudo journalctl --vacuum-size=100M 2>/dev/null || true
sudo journalctl --vacuum-time=2d 2>/dev/null || true

echo "--- SSM / amazon agent logs (truncate + remove huge rotated) ---"
# Root cause was: no space left writing amazon-ssm-agent.log / identity_config.json
for d in /var/log/amazon/ssm /var/log/amazon /var/lib/amazon/ssm; do
  if [[ -d "$d" ]]; then
    sudo find "$d" -type f \( -name '*.log' -o -name '*.log.*' -o -name '*.gz' -o -name '*.1' \) \
      -exec truncate -s 0 {} \; 2>/dev/null || true
    sudo find "$d" -type f \( -name '*.log.*' -o -name '*.gz' \) -size +1M -delete 2>/dev/null || true
  fi
done
# Classic package log path variants
sudo truncate -s 0 /var/log/amazon/ssm/amazon-ssm-agent.log 2>/dev/null || true
sudo truncate -s 0 /var/log/amazon/ssm/errors.log 2>/dev/null || true
sudo rm -f /var/log/amazon/ssm/*.log.[0-9]* /var/log/amazon/ssm/*.gz 2>/dev/null || true

echo "--- other large system logs ---"
sudo truncate -s 0 /var/log/syslog 2>/dev/null || true
sudo truncate -s 0 /var/log/auth.log 2>/dev/null || true
sudo find /var/log -type f \( -name '*.gz' -o -name '*.1' -o -name '*.old' \) -delete 2>/dev/null || true
sudo find /var/log -type f -name '*.log' -size +50M -exec truncate -s 0 {} \; 2>/dev/null || true

echo "--- apt cache ---"
sudo apt-get clean 2>/dev/null || true
sudo rm -rf /var/cache/apt/archives/*.deb 2>/dev/null || true

echo "--- /tmp and /var/tmp junk (keep crypto-2.0 alone) ---"
sudo find /tmp -xdev -type f -mtime +1 -delete 2>/dev/null || true
sudo find /var/tmp -xdev -type f -mtime +1 -delete 2>/dev/null || true
# Drop common build leftovers under /tmp only
sudo rm -rf /tmp/npm-* /tmp/node-compile-cache /tmp/pip-* /tmp/tmp.* 2>/dev/null || true

echo "--- snap old revisions (safe: keeps current only) ---"
if command -v snap >/dev/null 2>&1; then
  snap list --all 2>/dev/null | awk '/disabled/{print $1, $3}' | while read -r name rev; do
    sudo snap remove "$name" --revision="$rev" 2>/dev/null || true
  done
fi

echo "--- old kernels (keep running + newest; only if free space still tight) ---"
AVAIL_KB=$(df -Pk / | awk 'NR==2{print $4}')
if [[ "${AVAIL_KB:-0}" -lt 1048576 ]]; then
  # < ~1 GiB free: try autoremove of old kernels
  sudo apt-get -y autoremove --purge 2>/dev/null || true
fi

echo "--- docker prune (if docker present; unused only) ---"
if command -v docker >/dev/null 2>&1; then
  # Do not remove volumes (may hold LAB data)
  sudo docker system prune -af 2>/dev/null || true
  sudo docker builder prune -af 2>/dev/null || true
fi

echo "--- optional: large caches under /home/ubuntu (NOT crypto-2.0) ---"
# npm / pip / playwright caches only — never delete the repo
for cache in \
  /home/ubuntu/.npm/_cacache \
  /home/ubuntu/.cache/pip \
  /home/ubuntu/.cache/ms-playwright \
  /home/ubuntu/.cache/yarn \
  /var/cache/snapd; do
  if [[ -d "$cache" ]]; then
    echo "  clearing $cache"
    sudo rm -rf "$cache" 2>/dev/null || true
  fi
done

echo "=== df AFTER cleanup ==="
df -h / || true
df -i / || true
du -sh /var/log/amazon/ssm 2>/dev/null || true

echo "--- restart amazon-ssm-agent ---"
# Prefer snap unit on Ubuntu 22.04+, fall back to classic package
if systemctl list-unit-files 2>/dev/null | grep -q 'snap.amazon-ssm-agent.amazon-ssm-agent'; then
  sudo systemctl reset-failed snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || true
  sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service
  sudo systemctl is-active snap.amazon-ssm-agent.amazon-ssm-agent.service || true
elif systemctl list-unit-files 2>/dev/null | grep -q '^amazon-ssm-agent'; then
  sudo systemctl reset-failed amazon-ssm-agent 2>/dev/null || true
  sudo systemctl restart amazon-ssm-agent
  sudo systemctl is-active amazon-ssm-agent || true
else
  sudo systemctl restart amazon-ssm-agent 2>/dev/null || true
  sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null || true
fi

# Quick health hint (no secrets)
sudo journalctl -u snap.amazon-ssm-agent.amazon-ssm-agent.service -n 20 --no-pager 2>/dev/null \
  || sudo journalctl -u amazon-ssm-agent -n 20 --no-pager 2>/dev/null \
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
echo "Hints: root cause was often disk full (SSM cannot write logs/config)." >&2
echo "  Re-check df -h / on LAB; IAM profile atp-lab-builder-ssm-role; VPC egress to SSM." >&2
echo "  Re-run with --reboot if needed." >&2
exit 1
