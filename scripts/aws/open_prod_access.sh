#!/usr/bin/env bash
# Ensure PROD (atp-rebuild-2026) can be reached by EC2 Instance Connect and suggest Serial Console if SSH/SSM still fail.
# Run from your Mac with AWS CLI configured.
#
# Usage: ./scripts/aws/open_prod_access.sh

set -euo pipefail

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
# EC2 Instance Connect CIDR for ap-southeast-1 (browser-based Connect uses this)
EIC_CIDR="${EIC_CIDR:-3.0.5.32/29}"

SG_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query 'Reservations[0].Instances[0].SecurityGroups[0].GroupId' --output text 2>/dev/null)
if [ -z "$SG_ID" ] || [ "$SG_ID" = "None" ]; then
  echo "Could not get security group for $INSTANCE_ID"
  exit 1
fi

# Check if port 22 already allows EIC CIDR or 0.0.0.0/0
HAS_22=$(aws ec2 describe-security-groups --group-ids "$SG_ID" --region "$REGION" \
  --query "SecurityGroups[0].IpPermissions[?FromPort==\`22\` && ToPort==\`22\`].IpRanges[].CidrIp" --output text 2>/dev/null || true)
if echo "$HAS_22" | grep -q "0.0.0.0/0"; then
  echo "PROD SG $SG_ID already allows SSH (22) from 0.0.0.0/0 — Instance Connect and SSH should work if sshd is running."
elif echo "$HAS_22" | grep -q "$EIC_CIDR"; then
  echo "PROD SG $SG_ID already allows SSH (22) from EC2 Instance Connect CIDR $EIC_CIDR."
else
  echo "Adding SSH (22) from EC2 Instance Connect CIDR $EIC_CIDR to $SG_ID..."
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr "$EIC_CIDR" 2>/dev/null && echo "Added." || echo "Rule may already exist or another error occurred."
fi

echo ""
echo "If Instance Connect or SSH still fail (e.g. 'Error establishing SSH connection'):"
echo "  → Disk may be full (SSM/sshd can't start), or sshd/SSM agent may be stopped. Use EC2 Serial Console."
echo "  → See: docs/aws/PROD_ACCESS_WHEN_SSM_AND_SSH_FAIL.md (check df -h / first, then free space or resize)."
echo "  1. EC2 → Settings → EC2 Serial Console → Enable"
echo "  2. EC2 → Instances → atp-rebuild-2026 → Connect → EC2 serial console → Connect"
echo "  3. Log in and run: sudo systemctl start ssh && sudo systemctl start amazon-ssm-agent"
echo "  4. Retry Session Manager or Instance Connect, then run the nginx/openclaw fix."
