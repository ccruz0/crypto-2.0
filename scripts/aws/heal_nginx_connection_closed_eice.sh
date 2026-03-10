#!/usr/bin/env bash
# Heal ERR_CONNECTION_CLOSED / pending on https://dashboard.hilovivo.com/openclaw/
# Restarts nginx on PROD and re-applies openclaw proxy_pass to LAB:8080 on ALL sites-enabled
# files that mention openclaw. No SSM — uses EC2 Instance Connect + SSH only.
#
# Usage (from your Mac, repo root, AWS CLI configured):
#   ./scripts/aws/heal_nginx_connection_closed_eice.sh
#
# Requires: ec2-instance-connect:SendSSHPublicKey, ec2:DescribeInstances

set -euo pipefail

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"
LAB_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
PORT="${OPENCLAW_PORT:-8080}"

PUBLIC_IP=$(aws ec2 describe-instances --instance-ids "$INSTANCE_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
if [ -z "$PUBLIC_IP" ] || [ "$PUBLIC_IP" = "None" ]; then
  echo "Could not get public IP for $INSTANCE_ID"
  exit 1
fi

KEY_DIR=$(mktemp -d)
trap 'rm -rf "$KEY_DIR"' EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q

echo "Pushing temporary SSH key to PROD ($PUBLIC_IP)..."
aws ec2-instance-connect send-ssh-public-key \
  --instance-id "$INSTANCE_ID" \
  --instance-os-user ubuntu \
  --ssh-public-key "$(cat "$KEY_DIR/key.pub")" \
  --region "$REGION" >/dev/null

echo "Restarting nginx + syncing openclaw proxy on PROD..."
# Remote script: force all openclaw proxy_pass to LAB:PORT, then restart nginx
if ! ssh -o ConnectTimeout=25 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$PUBLIC_IP" "bash -s" << REMOTE
set -e
LAB="$LAB_IP"
PORT="$PORT"
PP="proxy_pass http://\${LAB}:\${PORT}/;"
echo "=== nginx -t (before) ==="
sudo nginx -t 2>&1 || true
echo "=== Sync openclaw proxy_pass in sites-enabled ==="
for f in /etc/nginx/sites-enabled/*; do
  [ -f "\$f" ] || continue
  grep -q openclaw "\$f" 2>/dev/null || continue
  echo "--- \$f ---"
  sudo sed -i \
    -e "s|proxy_pass http://52.77.216.100:8080/;|\$PP|g" \
    -e "s|proxy_pass http://52.77.216.100:8081/;|\$PP|g" \
    -e "s|proxy_pass http://\${LAB}:8081/;|\$PP|g" \
    "\$f" 2>/dev/null || true
done
echo "=== nginx -t (after) ==="
sudo nginx -t
echo "=== systemctl restart nginx ==="
sudo systemctl restart nginx
sleep 2
echo "=== curl local 443 /openclaw/ (expect 401 or 502 text, not connection closed) ==="
curl -sS -m 10 -I -k https://127.0.0.1/openclaw/ 2>&1 | head -12 || true
echo "=== tail error.log ==="
sudo tail -n 30 /var/log/nginx/error.log 2>/dev/null || true
REMOTE
then
  :
else
  echo ""
  echo "SSH to port 22 timed out. Run this block in EC2 Console → PROD → Instance Connect:"
  echo "--- paste from next line ---"
  cat << 'PASTE'
LAB=172.31.3.214
PORT=8080
PP="proxy_pass http://${LAB}:${PORT}/;"
for f in /etc/nginx/sites-enabled/*; do
  [ -f "$f" ] || continue
  grep -q openclaw "$f" 2>/dev/null || continue
  sudo sed -i \
    -e "s|proxy_pass http://52.77.216.100:8080/;|$PP|g" \
    -e "s|proxy_pass http://52.77.216.100:8081/;|$PP|g" \
    -e "s|proxy_pass http://${LAB}:8081/;|$PP|g" \
    "$f" 2>/dev/null || true
done
sudo nginx -t && sudo systemctl restart nginx
curl -sS -m 10 -I -k https://127.0.0.1/openclaw/ | head -12
PASTE
  echo "--- end paste ---"
  exit 1
fi

echo ""
echo "Done. Try in browser: https://dashboard.hilovivo.com/openclaw/"
echo "If still closed: check SG 443, try mobile hotspot, or AUTO_REBOOT=1 ./scripts/aws/bringup_dashboard_prod.sh"
