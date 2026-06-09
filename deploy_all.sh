#!/bin/bash
# Full deploy to AWS PROD (atp-rebuild-2026) via SSM.
# Mirrors .github/workflows/deploy_session_manager.yml so you can run the same deploy without pushing to main.
set -e

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "🚀 Deploy all → PROD (instance $INSTANCE_ID)"
echo "=========================================="

if ! command -v aws &>/dev/null; then
  echo "❌ AWS CLI not found. Install it and configure credentials."
  exit 1
fi

# Optional: wait for SSM to become Online before deploying (set DEPLOY_WAIT_FOR_SSM=1)
MAX_SSM_WAIT="${DEPLOY_SSM_WAIT_ATTEMPTS:-20}"
SSM_INTERVAL="${DEPLOY_SSM_WAIT_SECONDS:-30}"
if [ "${DEPLOY_WAIT_FOR_SSM:-0}" = "1" ]; then
  echo "   Waiting for SSM Online (max ${MAX_SSM_WAIT} x ${SSM_INTERVAL}s)..."
  for i in $(seq 1 "$MAX_SSM_WAIT"); do
    REACH=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" --region "$REGION" --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
    if [ "$REACH" = "Online" ]; then
      echo "   ✅ SSM Online (after ${i} check(s))."
      break
    fi
    echo "   ⏳ Attempt $i/$MAX_SSM_WAIT: SSM status=$REACH, waiting ${SSM_INTERVAL}s..."
    sleep "$SSM_INTERVAL"
  done
fi

# Quick SSM reachability check
echo "   Checking SSM reachability..."
REACH=$(aws ssm describe-instance-information --filters "Key=InstanceIds,Values=$INSTANCE_ID" --region "$REGION" --query "InstanceInformationList[0].PingStatus" --output text 2>/dev/null || true)
if [ "$REACH" != "Online" ] && [ -n "$REACH" ]; then
  echo "⚠️ Instance SSM status: $REACH (not Online). Deploy may fail with Undeliverable."
  echo "   Tip: run with DEPLOY_WAIT_FOR_SSM=1 to wait for the instance to come back."
fi
if [ -z "$REACH" ]; then
  echo "⚠️ Could not get SSM status for instance. Ensure the instance has SSM agent and IAM role."
fi

# 1) Inject GITHUB_TOKEN from SSM into .env.aws and secrets/runtime.env on EC2
echo ""
echo "🔑 Injecting GITHUB_TOKEN from SSM..."
INJECT_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd /home/ubuntu/crypto-2.0 || cd ~/crypto-2.0 || true",
    "GHTOKEN=$(aws ssm get-parameter --name /automated-trading-platform/prod/github_token --with-decryption --query Parameter.Value --output text 2>/dev/null || aws ssm get-parameter --name /openclaw/github-token --with-decryption --query Parameter.Value --output text 2>/dev/null || true)",
    "if [ -n \"$GHTOKEN\" ]; then grep -q \"^GITHUB_TOKEN=\" .env.aws 2>/dev/null && sed -i \"s|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$GHTOKEN|\" .env.aws || echo \"GITHUB_TOKEN=$GHTOKEN\" >> .env.aws; mkdir -p secrets; if grep -q \"^GITHUB_TOKEN=\" secrets/runtime.env 2>/dev/null; then sed -i \"s|^GITHUB_TOKEN=.*|GITHUB_TOKEN=$GHTOKEN|\" secrets/runtime.env; else echo \"GITHUB_TOKEN=$GHTOKEN\" >> secrets/runtime.env; fi; echo GITHUB_TOKEN injected; else echo No token in SSM; fi"
  ]' \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId" 2>/dev/null || true)

if [ -n "$INJECT_ID" ]; then
  aws ssm wait command-executed --command-id "$INJECT_ID" --instance-id "$INSTANCE_ID" --region "$REGION" 2>/dev/null || true
  echo "✅ GITHUB_TOKEN inject done"
else
  echo "⚠️ Could not send GITHUB_TOKEN inject (SSM may be unreachable)"
fi

# 2) Pull code + clone frontend on EC2
echo ""
echo "📥 Pulling code and cloning frontend on EC2..."
PULL_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/crypto-2.0 || cd /home/ubuntu/crypto-2.0 || { echo \"❌ Cannot find project directory\" && exit 1; }",
    "git pull origin main || echo \"Git pull failed, continuing...\"",
    "if [ -d frontend ]; then rm -rf frontend; fi",
    "git clone https://github.com/ccruz0/frontend.git frontend || { echo \"⚠️ Clone failed\" && exit 1; }",
    "grep -q \"version:\" frontend/src/app/page.tsx && echo \"✅ Frontend present\" || (echo \"⚠️ No version in frontend\" && exit 1)",
    "echo \"✅ Code updated\""
  ]' \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId")

aws ssm wait command-executed --command-id "$PULL_ID" --instance-id "$INSTANCE_ID" --region "$REGION" || true
PULL_STATUS=$(aws ssm get-command-invocation --command-id "$PULL_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query "Status" --output text 2>/dev/null || echo "Unknown")
echo "   Pull status: $PULL_STATUS"
aws ssm get-command-invocation --command-id "$PULL_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query "StandardOutputContent" --output text 2>/dev/null | tail -20

if [ "$PULL_STATUS" != "Success" ]; then
  echo "⚠️ Pull/clone had issues; continuing with rebuild anyway..."
fi

# 3) Rebuild and start all services (profile aws)
echo ""
echo "🐳 Rebuilding and starting all services (docker compose --profile aws)..."
BUILD_ID=$(aws ssm send-command \
  --instance-ids "$INSTANCE_ID" \
  --document-name "AWS-RunShellScript" \
  --parameters 'commands=[
    "cd ~/crypto-2.0 || cd /home/ubuntu/crypto-2.0 || { echo \"❌ Cannot find project directory\" && exit 1; }",
    "mkdir -p docs/agents/bug-investigations docs/agents/telegram-alerts docs/agents/execution-state && sudo chown -R 10001:10001 docs/agents/bug-investigations docs/agents/telegram-alerts docs/agents/execution-state || true",
    "bash scripts/aws/render_runtime_env.sh || true",
    "docker compose --profile aws down || true",
    "docker compose --profile aws build --no-cache",
    "docker image prune -f 2>/dev/null || true",
    "docker compose --profile aws up -d --build",
    "sleep 30",
    "for i in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20; do if curl -sf --connect-timeout 5 http://localhost:8002/ping_fast >/dev/null 2>&1; then echo \"✅ Backend healthy\"; break; fi; echo \"⏳ Backend not ready ($i/20)\"; sleep 10; done",
    "sudo systemctl restart nginx || true",
    "sleep 5",
    "docker compose --profile aws ps",
    "echo \"✅ Deployment completed\""
  ]' \
  --region "$REGION" \
  --output text \
  --query "Command.CommandId")

echo "   Command ID: $BUILD_ID"
echo "   Waiting for deploy (this can take several minutes)..."
for i in $(seq 1 36); do
  STATUS=$(aws ssm get-command-invocation --command-id "$BUILD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query "Status" --output text 2>/dev/null || echo "InProgress")
  if [ "$STATUS" = "Success" ] || [ "$STATUS" = "Failed" ]; then
    break
  fi
  printf "\r   ⏳ %ds " "$((i * 10))"
  sleep 10
done
echo ""

echo ""
echo "📄 Deploy output:"
aws ssm get-command-invocation \
  --command-id "$BUILD_ID" \
  --instance-id "$INSTANCE_ID" \
  --region "$REGION" \
  --query "StandardOutputContent" --output text 2>/dev/null || echo "(could not get output)"

FINAL=$(aws ssm get-command-invocation --command-id "$BUILD_ID" --instance-id "$INSTANCE_ID" --region "$REGION" --query "Status" --output text 2>/dev/null || echo "Unknown")
echo ""
if [ "$FINAL" = "Success" ]; then
  echo "🎉 Deploy all finished successfully."
  echo "   Dashboard: https://dashboard.hilovivo.com"
  echo "   Backend health: curl https://dashboard.hilovivo.com/api/ping_fast"
else
  echo "⚠️ Deploy finished with status: $FINAL"
  echo "   Check the output above and EC2 logs if needed."
  echo ""
  echo "   If SSM is ConnectionLost/Undeliverable, run deploy manually on the server:"
  echo "   ./scripts/aws/deploy_all_manual_commands.sh   # prints commands to paste in EC2 Instance Connect or SSH"
  exit 1
fi
