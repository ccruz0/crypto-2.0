#!/usr/bin/env bash
# One-time: add your local SSH public key to the EC2 instance so you can use
# deploy_aws.sh and ssh ubuntu@<ip> without EC2 Instance Connect each time.
# Uses EC2 Instance Connect to push a temp key, SSH in, append your key to authorized_keys.
set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
MY_KEY="${HOME}/.ssh/id_rsa.pub"

if [ ! -f "$MY_KEY" ]; then
  echo "❌ No public key at $MY_KEY. Create one with: ssh-keygen -t rsa -b 2048"
  exit 1
fi

PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "❌ Could not get public IP for instance $INSTANCE_ID"
  exit 1
fi

KEY_DIR=$(mktemp -d)
trap "rm -rf '$KEY_DIR'" EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q

echo "Pushing temporary key and adding your key to authorized_keys..."
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key.pub")" \
  --region "$REGION" >/dev/null

# Encode so we can pass over SSH without quoting issues
MY_PUB_B64=$(base64 < "$MY_KEY" | tr -d '\n')
ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$PUBLIC_IP" \
  "mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo $MY_PUB_B64 | base64 -d >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys && echo 'Key added.'"

echo "✅ Done. You can now use: ssh ubuntu@$PUBLIC_IP  and  HOST=ubuntu@$PUBLIC_IP ./deploy_aws.sh"
echo "   Or: HOST=ubuntu@dashboard.hilovivo.com ./deploy_aws.sh"
