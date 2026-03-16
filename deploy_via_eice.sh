#!/usr/bin/env bash
# Deploy to AWS PROD via EC2 Instance Connect + SSH (use when SSM is ConnectionLost).
# Pushes a temporary SSH key with the EC2 Instance Connect API, then runs deploy over SSH.
# Requires: AWS CLI, ssh-keygen, instance must have public IP and ec2-instance-connect.
set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "🚀 Deploy via EC2 Instance Connect + SSH → instance $INSTANCE_ID"
echo "=========================================="

# Resolve public IP
PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "❌ Could not get public IP for instance $INSTANCE_ID"
  exit 1
fi

# Temporary key (valid 60s on instance after send-ssh-public-key)
KEY_DIR=$(mktemp -d)
trap "rm -rf '$KEY_DIR'" EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q

echo "   Pushing temporary SSH key..."
if ! aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key.pub")" \
  --region "$REGION" 2>/dev/null; then
  echo "   ❌ send-ssh-public-key failed. Ensure:"
  echo "      - Security group allows port 22 from your IP (run: ./fix_security_group.sh)"
  echo "      - IAM allows ec2-instance-connect:SendSSHPublicKey"
  exit 1
fi
sleep 3

echo "   Connecting and running deploy (key valid 60s)..."
ssh -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o PubkeyAcceptedAlgorithms=+ssh-rsa -o HostKeyAlgorithms=+ssh-rsa \
  -i "$KEY_DIR/key" "ubuntu@$PUBLIC_IP" \
  "cd ~/automated-trading-platform 2>/dev/null || cd /home/ubuntu/automated-trading-platform || exit 1
   git pull origin main || true
   mkdir -p docs/agents/bug-investigations docs/agents/telegram-alerts docs/agents/execution-state && sudo chown -R 10001:10001 docs/agents/bug-investigations docs/agents/telegram-alerts docs/agents/execution-state || true
   docker compose --profile aws down || true
   docker compose --profile aws build --no-cache
   docker compose --profile aws up -d --build
   sleep 30
   for i in 1 2 3 4 5 6 7 8 9 10; do curl -sf --connect-timeout 5 http://localhost:8002/ping_fast >/dev/null && echo '✅ Backend healthy' && break; sleep 10; done
   sudo systemctl restart nginx 2>/dev/null || true
   docker compose --profile aws ps
   echo '✅ Deployment completed'"

echo ""
echo "🎉 Deploy finished. Dashboard: https://dashboard.hilovivo.com"
