#!/usr/bin/env bash
# Run the 10-second gateway model diagnostic on the LAB host via SSM.
# LAB has the gateway (127.0.0.1:8080) and openclaw.json with the token.
#
# Usage: ./scripts/openclaw/run_gateway_model_diagnostic_via_ssm.sh
# Optional: LAB_INSTANCE_ID=i-xxx AWS_REGION=ap-southeast-1 ./scripts/openclaw/run_gateway_model_diagnostic_via_ssm.sh

set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-southeast-1}"
LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$REPO_ROOT"

if ! command -v aws &>/dev/null; then
  echo "AWS CLI required. Install and configure aws cli."
  exit 1
fi

echo "=== Gateway model diagnostic via SSM (LAB $LAB_INSTANCE_ID) ==="
INSTANCE_STATE=$(aws ec2 describe-instances --instance-ids "$LAB_INSTANCE_ID" --region "$AWS_REGION" \
  --query 'Reservations[0].Instances[0].State.Name' --output text 2>/dev/null || echo "Unknown")
echo "Instance state: $INSTANCE_STATE"

STATUS=$(aws ssm describe-instance-information --region "$AWS_REGION" \
  --filters "Key=InstanceIds,Values=$LAB_INSTANCE_ID" \
  --query 'InstanceInformationList[0].PingStatus' --output text 2>/dev/null || echo "NotFound")
echo "SSM PingStatus: $STATUS"

run_via_eice() {
  LAB_IP=$(aws ec2 describe-instances --instance-ids "$LAB_INSTANCE_ID" --region "$AWS_REGION" \
    --query "Reservations[0].Instances[0].PublicIpAddress" --output text 2>/dev/null || true)
  if [[ -z "$LAB_IP" || "$LAB_IP" == "None" ]]; then
    echo "LAB has no public IP (e.g. stopped or no elastic IP). Start the instance or use SSM when Online."
    return 1
  fi
  KEY_DIR=$(mktemp -d)
  trap "rm -rf '$KEY_DIR'" RETURN
  ssh-keygen -t rsa -b 2048 -f "$KEY_DIR/key" -N "" -q 2>/dev/null
  if ! aws ec2-instance-connect send-ssh-public-key --instance-id "$LAB_INSTANCE_ID" \
    --instance-os-user ubuntu --ssh-public-key "$(cat "$KEY_DIR/key.pub")" --region "$AWS_REGION" 2>/dev/null; then
    echo "EC2 Instance Connect failed (IAM or SG 22 from your IP). Run diagnostic manually on LAB."
    return 1
  fi
  SSH_ERR=$(mktemp)
  OUT=$(ssh -o ConnectTimeout=15 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
    -i "$KEY_DIR/key" "ubuntu@$LAB_IP" "bash -s" 2>"$SSH_ERR" << 'ENDSSH'
C=/opt/openclaw/openclaw.json; [ -f /opt/openclaw/home-data/openclaw.json ] && C=/opt/openclaw/home-data/openclaw.json
T=$(jq -r ".gateway.auth.token // empty" "$C" 2>/dev/null); [ -z "$T" ] && echo HTTP_CODE=401 && exit 0
CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8080/v1/responses -H "Authorization: Bearer $T" -H "Content-Type: application/json" -d '{"model":"unsupported/fake-model-id","input":"gateway model routing test"}' 2>/dev/null); echo HTTP_CODE=${CODE:-000}
ENDSSH
  )
  SSH_EXIT=$?
  if [[ $SSH_EXIT -ne 0 ]]; then
    echo "SSH to LAB failed (exit $SSH_EXIT). LAB SG may not allow TCP 22 from your IP."
    [[ -s "$SSH_ERR" ]] && cat "$SSH_ERR"
    rm -f "$SSH_ERR"
    return 1
  fi
  rm -f "$SSH_ERR"
  CODE=$(echo "$OUT" | grep -oE 'HTTP_CODE=[0-9]+' | cut -d= -f2)
  if [[ -n "$CODE" ]]; then
    echo ""
    echo "--- EICE stdout ---"
    echo "$OUT"
    echo ""
    echo "=== Result: $CODE ==="
    case "$CODE" in
      400) echo "Gateway contract implemented correctly (read body.model, validated, rejected fake model)." ;;
      200) echo "Gateway is ignoring model — implement contract in OpenClaw repo (see docs/openclaw/GATEWAY_MODEL_CONTRACT_IMPLEMENTATION_CHECKLIST.md)." ;;
      401) echo "Token wrong or missing — check gateway.auth.token in openclaw.json on LAB." ;;
      404) echo "Wrong path — in OpenClaw repo search for /responses or OpenResponses." ;;
      *)   echo "Unexpected code. Check gateway and docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md." ;;
    esac
    return 0
  fi
  echo "EICE ran but could not parse HTTP_CODE. Output: $OUT"
  return 1
}

if [[ "$STATUS" != "Online" ]]; then
  echo "LAB not Online for SSM. Trying EC2 Instance Connect + SSH..."
  if run_via_eice; then
    exit 0
  fi
  echo ""
  echo "Run the diagnostic manually on LAB (SSH or AWS Console → Connect → EC2 Instance Connect):"
  echo "  TOKEN=\$(jq -r '.gateway.auth.token' /opt/openclaw/openclaw.json)"
  echo "  curl -s -o /dev/null -w \"%{http_code}\n\" -X POST http://127.0.0.1:8080/v1/responses \\"
  echo "    -H \"Authorization: Bearer \$TOKEN\" -H \"Content-Type: application/json\" \\"
  echo "    -d '{\"model\":\"unsupported/fake-model-id\",\"input\":\"gateway model routing test\"}'"
  exit 1
fi

# Run on LAB: one-liner gets token, curls with unsupported model, prints HTTP_CODE=NNN
COMMAND_ID=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "C=/opt/openclaw/openclaw.json; [ -f /opt/openclaw/home-data/openclaw.json ] && C=/opt/openclaw/home-data/openclaw.json",
    "T=$(jq -r \".gateway.auth.token // empty\" \"$C\" 2>/dev/null); [ -z \"$T\" ] && echo HTTP_CODE=401 && exit 0",
    "CODE=$(curl -s -o /dev/null -w \"%{http_code}\" -X POST http://127.0.0.1:8080/v1/responses -H \"Authorization: Bearer $T\" -H \"Content-Type: application/json\" -d \"{\\\"model\\\":\\\"unsupported/fake-model-id\\\",\\\"input\\\":\\\"gateway model routing test\\\"}\" 2>/dev/null); echo HTTP_CODE=${CODE:-000}"
  ]' \
  --query 'Command.CommandId' \
  --output text 2>/dev/null)

if [[ -z "$COMMAND_ID" ]]; then
  echo "Failed to send SSM command."
  exit 1
fi

echo "Command ID: $COMMAND_ID (waiting up to 30s)..."
for i in $(seq 1 30); do
  S=$(aws ssm get-command-invocation \
    --command-id "$COMMAND_ID" \
    --instance-id "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$S" == "Success" || "$S" == "Failed" || "$S" == "Cancelled" ]]; then
    break
  fi
  sleep 1
done

OUT=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardOutputContent' --output text 2>/dev/null || echo "")
ERR=$(aws ssm get-command-invocation \
  --command-id "$COMMAND_ID" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query 'StandardErrorContent' --output text 2>/dev/null || echo "")

echo ""
echo "--- Stdout ---"
echo "$OUT"
if [[ -n "$ERR" ]]; then
  echo "--- Stderr ---"
  echo "$ERR"
fi

CODE=$(echo "$OUT" | grep -oE 'HTTP_CODE=[0-9]+' | cut -d= -f2)
echo ""
if [[ -z "$CODE" ]]; then
  echo "Could not parse HTTP code from output. Check stdout above."
  exit 1
fi

echo "=== Result: $CODE ==="
case "$CODE" in
  400) echo "Gateway contract implemented correctly (read body.model, validated, rejected fake model)." ;;
  200) echo "Gateway is ignoring model — implement contract in OpenClaw repo (see docs/openclaw/GATEWAY_MODEL_CONTRACT_IMPLEMENTATION_CHECKLIST.md)." ;;
  401) echo "Token wrong or missing — check gateway.auth.token in openclaw.json on LAB." ;;
  404) echo "Wrong path — in OpenClaw repo search for /responses or OpenResponses." ;;
  *)   echo "Unexpected code. Check gateway and docs/GATEWAY_MODEL_ROUTING_AND_FAILOVER_COMPATIBILITY.md." ;;
esac
