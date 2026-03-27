#!/usr/bin/env bash
# Start OpenClaw on LAB by: push temp key to LAB and PROD, copy key to PROD, SSH from PROD to LAB.
# Run right after fix_504_via_eice.sh or standalone. Key is valid 60s — minimal delay between push and SSH.
set -e
PROD_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
LAB_ID="${OPENCLAW_LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
REGION="${AWS_REGION:-ap-southeast-1}"
LAB_IP="${LAB_PRIVATE_IP:-172.31.3.214}"

PROD_PUBLIC=$(aws ec2 describe-instances --instance-ids "$PROD_ID" --region "$REGION" \
  --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
[ -z "$PROD_PUBLIC" ] || [ "$PROD_PUBLIC" = "None" ] && { echo "No PROD public IP"; exit 1; }

KEY_DIR=$(mktemp -d)
trap "rm -rf '$KEY_DIR'" EXIT
ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q

echo "Pushing key to LAB and PROD (60s validity)..."
aws ec2-instance-connect send-ssh-public-key --instance-id "$LAB_ID" --instance-os-user ubuntu --ssh-public-key "$(cat "$KEY_DIR/key.pub")" --region "$REGION" >/dev/null
aws ec2-instance-connect send-ssh-public-key --instance-id "$PROD_ID" --instance-os-user ubuntu --ssh-public-key "$(cat "$KEY_DIR/key.pub")" --region "$REGION" >/dev/null

echo "Copying key to PROD and running PROD->LAB..."
cat "$KEY_DIR/key" | ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -i "$KEY_DIR/key" "ubuntu@$PROD_PUBLIC" "cat > /tmp/labkey && chmod 600 /tmp/labkey && ssh -i /tmp/labkey -o ConnectTimeout=12 -o StrictHostKeyChecking=no ubuntu@$LAB_IP 'cd /home/ubuntu/crypto-2.0 2>/dev/null && NONINTERACTIVE=1 sudo bash scripts/openclaw/check_and_start_openclaw.sh' && rm -f /tmp/labkey" 2>/dev/null && echo "OpenClaw started on LAB." || echo "PROD->LAB SSH failed (key may have expired or LAB SG blocks 22 from PROD)."
