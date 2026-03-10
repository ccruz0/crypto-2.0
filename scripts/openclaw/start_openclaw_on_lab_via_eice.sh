#!/usr/bin/env bash
# Start OpenClaw on LAB via EC2 Instance Connect + SSH. Use when SSM is ConnectionLost.
# Run from your machine with AWS CLI configured.
set -e
LAB_ID="${OPENCLAW_LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"

LAB_IP=$(aws ec2 describe-instances --instance-ids "$LAB_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
if [ -z "$LAB_IP" ] || [ "$LAB_IP" = "None" ]; then
  echo "LAB has no public IP. Use SSM when Online: aws ssm start-session --target $LAB_ID --region $REGION"
  exit 1
fi

KEY_DIR=$(mktemp -d)
trap "rm -rf '$KEY_DIR'" EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q

echo "Pushing temporary SSH key to LAB ($LAB_IP)..."
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$LAB_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key.pub")" \
  --region "$REGION" || { echo "SendSSHPublicKey failed (check IAM + LAB has ec2-instance-connect)"; exit 1; }

echo "Starting OpenClaw on LAB..."
set +e
ssh -o ConnectTimeout=12 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$LAB_IP" "bash -s" << 'INNER'
REPO="$HOME/automated-trading-platform"
[ -d "$REPO" ] || REPO="/home/ubuntu/automated-trading-platform"
cd "$REPO" 2>/dev/null || { echo "Repo not found on LAB"; exit 1; }
export NONINTERACTIVE=1
sudo bash scripts/openclaw/check_and_start_openclaw.sh 2>/dev/null || {
  echo "Trying systemctl or docker..."
  sudo systemctl start openclaw 2>/dev/null || true
  sudo docker start openclaw 2>/dev/null || true
  sudo docker ps -a | grep -i openclaw || true
}
echo ""
echo "Checking port 8080 (docker-compose.openclaw.yml default)..."
ss -lntp 2>/dev/null | grep -E ':8080|:8081' || sudo ss -lntp | grep -E ':8080|:8081' || true
curl -sS -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8080/ 2>/dev/null || curl -sS -m 3 -o /dev/null -w "%{http_code}" http://127.0.0.1:8081/ 2>/dev/null || echo "no response"
INNER
SSH_EXIT=$?
set -e

if [[ "$SSH_EXIT" -ne 0 ]]; then
  echo ""
  echo "SSH to LAB timed out or failed (exit $SSH_EXIT)."
  echo "LAB SG must allow inbound TCP 22 from YOUR IP (or use Session Manager when Online)."
  echo "Alternative — AWS Console → EC2 → atp-lab-ssm-clean → Connect → EC2 Instance Connect, then:"
  echo "  cd /home/ubuntu/automated-trading-platform && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh"
  echo "Or clone repo on LAB if missing: git clone https://github.com/ccruz0/automated-trading-platform.git"
  exit "$SSH_EXIT"
fi

echo ""
echo "Done. Test: https://dashboard.hilovivo.com/openclaw/ (expect 401, not 504)"
