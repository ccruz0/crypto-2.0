#!/usr/bin/env bash
# Restore SSM on PROD when PingStatus is ConnectionLost.
# 1) Reboot instance. 2) If still ConnectionLost: add SSH from this machine's IP, connect via EC2 Instance Connect, restart SSM agent, revoke rule.
set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "=== Restore SSM on PROD ($INSTANCE_ID) ==="

# Resolve instance SG and public IP
SG_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].SecurityGroups[0].GroupId" --output text 2>/dev/null || true)
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
if [ -z "$SG_ID" ] || [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "Could not get instance SG or public IP"
  exit 1
fi

# Step 1: Reboot
echo "Step 1: Rebooting instance..."
aws ec2 reboot-instances --region "$REGION" --instance-ids "$INSTANCE_ID" >/dev/null
echo "Waiting 150s for instance to come back..."
sleep 150

STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
if [ "$STATUS" = "Online" ]; then
  echo "SSM is Online after reboot."
  exit 0
fi

echo "SSM still $STATUS. Step 2: Restart SSM agent via EC2 Instance Connect..."

# Get our public IP for temporary SSH rule
MY_IP=$(curl -sS --max-time 8 https://ifconfig.me/ip 2>/dev/null || curl -sS --max-time 8 https://icanhazip.com 2>/dev/null || true)
if [ -z "$MY_IP" ]; then
  echo "Could not get this machine's public IP. Add SSH (22) from your IP to SG $SG_ID and run: ssh ubuntu@$PUBLIC_IP 'sudo systemctl restart amazon-ssm-agent; sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null'"
  exit 1
fi

# Add SSH from our IP (idempotent: may already exist)
echo "Adding temporary SSH (22) from $MY_IP to $SG_ID..."
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
  --protocol tcp --port 22 --cidr "$MY_IP/32" 2>/dev/null || true

cleanup_sg() {
  aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$SG_ID" \
    --protocol tcp --port 22 --cidr "$MY_IP/32" 2>/dev/null || true
  echo "Revoked temporary SSH rule."
}
# Temp key and push via EC2 Instance Connect
KEY_DIR=$(mktemp -d)
trap 'cleanup_sg; rm -rf "$KEY_DIR"' EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q

echo "Pushing temporary SSH key..."
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key.pub")" \
  --region "$REGION" >/dev/null

echo "Restarting SSM agent on instance..."
ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$PUBLIC_IP" \
  "sudo systemctl restart amazon-ssm-agent 2>/dev/null; sudo systemctl restart snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null; echo 'Restart done.'"

echo "Waiting 90s for agent to re-register..."
sleep 90

STATUS=$(aws ssm describe-instance-information --region "$REGION" \
  --filters "Key=InstanceIds,Values=$INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
if [ "$STATUS" = "Online" ]; then
  echo "SSM PingStatus: Online."
  exit 0
fi

# Step 3: Allow PROD SG to SSM VPC endpoints (if endpoints exist and only LAB SG was allowed)
echo "SSM still $STATUS. Step 3: Checking VPC endpoints for SSM..."
VPC_ID=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" --query 'Reservations[0].Instances[0].VpcId' --output text 2>/dev/null)
for ep in $(aws ec2 describe-vpc-endpoints --region "$REGION" --filters "Name=vpc-id,Values=$VPC_ID" "Name=service-name,Values=*ssm*,*ec2messages*" --query 'VpcEndpoints[*].Groups[*].GroupId' --output text 2>/dev/null | tr '\t' '\n' | sort -u); do
  aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$ep" --protocol tcp --port 443 --source-group "$SG_ID" 2>/dev/null && echo "Added $SG_ID to endpoint SG $ep" || true
done
echo "Waiting 45s for agent to reach SSM..."
sleep 45
STATUS=$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
echo "SSM PingStatus: $STATUS"
[ "$STATUS" = "Online" ] && exit 0

# Step 4: Replace IAM instance profile to refresh credentials
echo "SSM still $STATUS. Step 4: Replacing IAM instance profile..."
ASSOC_ID=$(aws ec2 describe-iam-instance-profile-associations --region "$REGION" --filters "Name=instance-id,Values=$INSTANCE_ID" --query 'IamInstanceProfileAssociations[0].AssociationId' --output text 2>/dev/null)
PROFILE_ARN=$(aws ec2 describe-iam-instance-profile-associations --region "$REGION" --filters "Name=instance-id,Values=$INSTANCE_ID" --query 'IamInstanceProfileAssociations[0].IamInstanceProfile.Arn' --output text 2>/dev/null)
if [ -n "$ASSOC_ID" ] && [ "$ASSOC_ID" != "None" ] && [ -n "$PROFILE_ARN" ]; then
  aws ec2 replace-iam-instance-profile-association --region "$REGION" --association-id "$ASSOC_ID" --iam-instance-profile "Arn=$PROFILE_ARN" >/dev/null
  echo "Waiting 90s after IAM replace..."
  sleep 90
  STATUS=$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$INSTANCE_ID" --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
  echo "SSM PingStatus: $STATUS"
  [ "$STATUS" = "Online" ] && exit 0
fi

# Step 5: If still ConnectionLost, collect agent logs for diagnosis (re-add SSH, run, revoke)
echo "SSM still $STATUS. Collecting agent logs on instance..."
aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$MY_IP/32" 2>/dev/null || true
sleep 2
KEY_DIR2=$(mktemp -d)
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR2/key" -N "" -q 2>/dev/null
aws ec2-instance-connect send-ssh-public-key --instance-id "$INSTANCE_ID" --instance-os-user ubuntu --ssh-public-key "$(cat "$KEY_DIR2/key.pub")" --region "$REGION" >/dev/null 2>&1
echo "--- SSM agent status ---"
ssh -o ConnectTimeout=12 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i "$KEY_DIR2/key" "ubuntu@$PUBLIC_IP" "sudo systemctl status amazon-ssm-agent 2>/dev/null || sudo systemctl status snap.amazon-ssm-agent.amazon-ssm-agent.service 2>/dev/null; echo '--- Agent log (last 30) ---'; sudo journalctl -u amazon-ssm-agent -n 30 --no-pager 2>/dev/null || sudo journalctl -u snap.amazon-ssm-agent.amazon-ssm-agent.service -n 30 --no-pager 2>/dev/null || sudo tail -30 /var/log/amazon/ssm/amazon-ssm-agent.log 2>/dev/null" 2>/dev/null || true
rm -rf "$KEY_DIR2"
aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$SG_ID" --protocol tcp --port 22 --cidr "$MY_IP/32" 2>/dev/null || true
echo "See docs/audit/SSM_SESSION_MANAGER_CONNECTIVITY_AUDIT.md for full diagnosis."
exit 1
