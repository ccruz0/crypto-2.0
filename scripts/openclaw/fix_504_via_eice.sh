#!/usr/bin/env bash
# Fix 504 on /openclaw/ by running the Nginx proxy fix on PROD via EC2 Instance Connect + SSH.
# Then (if LAB is reachable from PROD) start OpenClaw on LAB using the same temp key pushed to both.
# No SSM required. Uses temporary SSH keys (60s). Run from your machine with AWS CLI configured.
set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
LAB_ID="${OPENCLAW_LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"
LAB_PRIVATE_IP="${LAB_PRIVATE_IP:-172.31.3.214}"

PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "Could not get public IP for $INSTANCE_ID"
  exit 1
fi

KEY_DIR=$(mktemp -d)
trap "rm -rf '$KEY_DIR'" EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q
# Same key for LAB so we can copy it to PROD and SSH from PROD to LAB
cp "$KEY_DIR/key" "$KEY_DIR/key_lab"
cp "$KEY_DIR/key.pub" "$KEY_DIR/key_lab.pub"

echo "Pushing temporary SSH key to PROD..."
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key.pub")" \
  --region "$REGION" >/dev/null

echo "Pushing same key to LAB (for PROD->LAB SSH)..."
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$LAB_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key_lab.pub")" \
  --region "$REGION" >/dev/null 2>&1 || true

REPO="\$HOME/automated-trading-platform"
echo "Running OpenClaw 504 fix on PROD ($PUBLIC_IP)..."
# Copy LAB key to PROD so PROD can SSH to LAB
cat "$KEY_DIR/key_lab" | ssh -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$PUBLIC_IP" "cat > /tmp/labkey && chmod 600 /tmp/labkey"

ssh -o ConnectTimeout=20 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$PUBLIC_IP" "bash -s" << INNER
REPO="$HOME/automated-trading-platform"
[ -d "$REPO" ] || REPO="/home/ubuntu/automated-trading-platform"
if [ ! -d "$REPO" ]; then echo "Repo not found"; exit 1; fi
cd "$REPO"
sudo rm -f /etc/nginx/sites-enabled/default.bak504 2>/dev/null || true
sudo systemctl start nginx 2>/dev/null || true
git pull origin main 2>/dev/null || true
export LAB_PRIVATE_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
# Default 8080 matches docker-compose.openclaw.yml (8080:18789). Use 8081 only if LAB publishes 8081.
export OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"
if [ -f scripts/openclaw/fix_openclaw_proxy_prod.sh ]; then
  sudo -E bash scripts/openclaw/fix_openclaw_proxy_prod.sh
fi
# Normalize every sites-enabled file that mentions openclaw (502 fix when active server is not default).
PP="proxy_pass http://${LAB_PRIVATE_IP}:${OPENCLAW_PORT}/;"
for ngf in /etc/nginx/sites-enabled/*; do
  [ -f "$ngf" ] || continue
  grep -q openclaw "$ngf" 2>/dev/null || continue
  sudo sed -i "s|proxy_pass http://52.77.216.100:8080/;|$PP|g" "$ngf" 2>/dev/null || true
  sudo sed -i "s|proxy_pass http://52.77.216.100:8081/;|$PP|g" "$ngf" 2>/dev/null || true
  if [ "$OPENCLAW_PORT" = "8080" ]; then
    sudo sed -i "s|proxy_pass http://${LAB_PRIVATE_IP}:8081/;|$PP|g" "$ngf" 2>/dev/null || true
  fi
  sudo sed -i "s|proxy_pass http://${LAB_PRIVATE_IP}:8080/;|$PP|g" "$ngf" 2>/dev/null || true
done
# If force script exists (after pull), run it to catch any other upstream patterns
if [ -f scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh ]; then
  sudo -E bash scripts/openclaw/force_openclaw_proxy_8080_on_prod.sh || true
fi
sudo rm -f /etc/nginx/sites-enabled/default.bak504 2>/dev/null || true
sudo nginx -t && (sudo systemctl is-active nginx --quiet && sudo systemctl reload nginx || sudo systemctl start nginx) && echo "Nginx running."
echo ""
echo "Verifying..."
curl -sS -m 8 -I "https://dashboard.hilovivo.com/openclaw/" 2>/dev/null | head -8 || true
echo ""
echo "Starting OpenClaw on LAB from PROD (ssh to $LAB_PRIVATE_IP with temp key)..."
ssh -i /tmp/labkey -o ConnectTimeout=15 -o StrictHostKeyChecking=no -o BatchMode=yes ubuntu@$LAB_PRIVATE_IP 'for d in /home/ubuntu/automated-trading-platform /home/ubuntu/crypto-2.0; do [ -f "$d/scripts/openclaw/check_and_start_openclaw.sh" ] && cd "$d" && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh && exit 0; done; echo "LAB script not found (clone repo on LAB or run compose manually)"' 2>/dev/null && echo "OpenClaw started on LAB." || echo "(PROD could not SSH to LAB; start OpenClaw on LAB via Instance Connect — see docs/runbooks/START_OPENCLAW_ON_LAB_CONSOLE.md)"
rm -f /tmp/labkey
INNER

echo ""
echo "Done. Test: https://dashboard.hilovivo.com/openclaw/ (expect 401, not 504)"
