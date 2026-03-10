#!/usr/bin/env bash
# Apply OpenClaw nginx fix on PROD by setting LAB upstream IP/port and WS path.
# Tries SSM send-command; if Undeliverable, prints commands to run in an SSM session.
set -euo pipefail

INSTANCE_ID="${INSTANCE_ID:-i-087953603011543c5}"
REGION="${REGION:-ap-southeast-1}"
LAB_PRIVATE_IP="${LAB_PRIVATE_IP:-172.31.3.214}"
OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"

manual_instructions() {
  echo "Run the fix manually in an SSM session:"
  echo ""
  echo "  aws ssm start-session --target $INSTANCE_ID --region $REGION"
  echo ""
  echo "Then paste (port ${OPENCLAW_PORT} + WebSocket path /ws):"
  echo ""
  echo "  for f in /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/dashboard.conf; do"
  echo "    [ -f \"\$f\" ] && sudo sed -i 's/${LAB_PRIVATE_IP}:8080/${LAB_PRIVATE_IP}:${OPENCLAW_PORT}/g' \"\$f\" && sudo sed -i 's/${LAB_PRIVATE_IP}:8081/${LAB_PRIVATE_IP}:${OPENCLAW_PORT}/g' \"\$f\" && echo \"Updated \$f\""
  echo "  done"
  echo "  # Fix WebSocket proxy: first occurrence of :${OPENCLAW_PORT}/; -> :${OPENCLAW_PORT}/ws; (so backend receives /ws)"
  echo "  [ -f /etc/nginx/sites-enabled/dashboard.conf ] && sudo sed -i '0,/${LAB_PRIVATE_IP//./\\\\.}:${OPENCLAW_PORT}\\/;/s/${LAB_PRIVATE_IP//./\\\\.}:${OPENCLAW_PORT}\\/;/${LAB_PRIVATE_IP}:${OPENCLAW_PORT}\\/ws;/' /etc/nginx/sites-enabled/dashboard.conf && echo \"Updated WS path in dashboard.conf\""
  echo "  sudo nginx -t && sudo systemctl reload nginx"
  echo ""
  echo "See: docs/runbooks/APPLY_OPENCLAW_NGINX_8081_PROD.md"
}

echo "🔧 OpenClaw nginx fix (PROD -> ${LAB_PRIVATE_IP}:${OPENCLAW_PORT})"
echo "   Instance: $INSTANCE_ID"
echo ""

NGINX_FIX_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "for f in /etc/nginx/sites-enabled/default /etc/nginx/sites-enabled/dashboard.conf; do [ -f \"$f\" ] && sudo sed -i \"s/'"$LAB_PRIVATE_IP"':8080/'"$LAB_PRIVATE_IP"':'"$OPENCLAW_PORT"'/g\" \"$f\" && sudo sed -i \"s/'"$LAB_PRIVATE_IP"':8081/'"$LAB_PRIVATE_IP"':'"$OPENCLAW_PORT"'/g\" \"$f\"; done",
    "sudo sed -i \"0,/'"$LAB_PRIVATE_IP"':'"$OPENCLAW_PORT"'\\/;/s/'"$LAB_PRIVATE_IP"':'"$OPENCLAW_PORT"'\\/;/'"$LAB_PRIVATE_IP"':'"$OPENCLAW_PORT"'\\/ws;/\" /etc/nginx/sites-enabled/dashboard.conf 2>/dev/null || true",
    "sudo nginx -t && sudo systemctl reload nginx && echo OK"
  ]' \
  --region "$REGION" \
  --timeout-seconds 30 \
  --output text \
  --query "Command.CommandId" 2>/dev/null || true)

if [[ -z "$NGINX_FIX_ID" ]]; then
  echo "⚠️  send-command failed or returned no ID."
  manual_instructions
  exit 1
fi

echo "   Command ID: $NGINX_FIX_ID"
echo "   Waiting 15s..."
sleep 15

STATUS=$(aws ssm get-command-invocation \
  --command-id "$NGINX_FIX_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "Status" --output text 2>/dev/null || echo "Unknown")
DETAILS=$(aws ssm get-command-invocation \
  --command-id "$NGINX_FIX_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StatusDetails" --output text 2>/dev/null || echo "")

if [[ "$STATUS" == "Success" ]]; then
  echo "✅ Fix applied. Check https://dashboard.hilovivo.com/openclaw/"
  exit 0
fi

echo "⚠️  Status: $STATUS ${DETAILS:+($DETAILS)}"
if [[ "$DETAILS" == "Undeliverable" ]]; then
  echo ""
  manual_instructions
  exit 1
fi

aws ssm get-command-invocation \
  --command-id "$NGINX_FIX_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "[StandardOutputContent,StandardErrorContent]" --output text 2>/dev/null || true
exit 1
