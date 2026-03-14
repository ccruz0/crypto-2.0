#!/usr/bin/env bash
# Build OpenClaw from GitHub on LAB, then restart the container with the new image.
# No GHCR push needed. Requires gateway model contract to be on the chosen branch (e.g. main).
#
# Usage:
#   ./scripts/openclaw/build_on_lab_and_restart.sh
#   OPENCLAW_REPO_URL=https://github.com/ccruz0/openclaw.git OPENCLAW_BRANCH=main ./scripts/openclaw/build_on_lab_and_restart.sh
#
set -euo pipefail

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
OPENCLAW_REPO_URL="${OPENCLAW_REPO_URL:-https://github.com/ccruz0/openclaw.git}"
OPENCLAW_BRANCH="${OPENCLAW_BRANCH:-main}"
BUILD_DIR="${OPENCLAW_BUILD_DIR:-/home/ubuntu/openclaw-build}"
OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/opt/openclaw}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_CONFIG_DIR/openclaw.json}"
OPENCLAW_HOME_DIR="${OPENCLAW_HOME_DIR:-/opt/openclaw/home-data}"
ATP_REPO_PATH="${ATP_REPO_PATH:-/home/ubuntu/automated-trading-platform}"
OPENCLAW_ALLOWED_ORIGINS="${OPENCLAW_ALLOWED_ORIGINS:-https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789}"
OPENCLAW_TRUSTED_PROXIES="${OPENCLAW_TRUSTED_PROXIES:-172.31.32.169}"
OPENCLAW_ACP_DEFAULT_AGENT="${OPENCLAW_ACP_DEFAULT_AGENT:-codex}"

echo "==> Build OpenClaw on LAB from $OPENCLAW_REPO_URL ($OPENCLAW_BRANCH) and restart container"
echo "    LAB: $LAB_INSTANCE_ID  Build dir: $BUILD_DIR"
echo ""

# Config builder: one line so JSON params don't get control chars
build_cfg="OPENCLAW_ALLOWED_ORIGINS=$OPENCLAW_ALLOWED_ORIGINS OPENCLAW_TRUSTED_PROXIES=$OPENCLAW_TRUSTED_PROXIES OPENCLAW_ACP_DEFAULT_AGENT=$OPENCLAW_ACP_DEFAULT_AGENT OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_PATH python3 -c \"import json,os,pathlib,secrets; o=[s.strip() for s in __import__('os').environ.get('OPENCLAW_ALLOWED_ORIGINS','').split(',') if s.strip()]; px=[s.strip() for s in __import__('os').environ.get('OPENCLAW_TRUSTED_PROXIES','').split(',') if s.strip()]; acp_agent=__import__('os').environ.get('OPENCLAW_ACP_DEFAULT_AGENT','codex').strip(); p=pathlib.Path(__import__('os').environ['OPENCLAW_CONFIG_PATH']); p.parent.mkdir(parents=True,exist_ok=True); cfg=json.loads(p.read_text()) if p.exists() else {}; g=cfg.setdefault('gateway',{}); g.setdefault('controlUi',{})['allowedOrigins']=o; g['trustedProxies']=px if px else g.get('trustedProxies',[]); a=g.setdefault('auth',{}); t=(a.get('token')or '').strip() or secrets.token_hex(24); a['token']=t; acp=cfg.setdefault('acp',{}); acp['defaultAgent']=acp_agent; p.write_text(json.dumps(cfg)); print('OPENCLAW_GATEWAY_TOKEN='+t)\""

run_cmd="sudo docker run -d --restart unless-stopped -p 8080:18789 -e OPENCLAW_ALLOWED_ORIGINS=$OPENCLAW_ALLOWED_ORIGINS -e OPENCLAW_TRUSTED_PROXIES=$OPENCLAW_TRUSTED_PROXIES -e OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_PATH -v $OPENCLAW_CONFIG_DIR:$OPENCLAW_CONFIG_DIR -v $OPENCLAW_HOME_DIR:/home/node/.openclaw -v $ATP_REPO_PATH:/home/node/.openclaw/workspace/atp:ro -v $OPENCLAW_HOME_DIR/agents:/home/node/openclaw/agents --name openclaw openclaw:local"

# Escape for JSON: backslash and double-quote
escape_json() { echo "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'; }
build_cfg_esc=$(escape_json "$build_cfg")
run_cmd_esc=$(escape_json "$run_cmd")

# Clone or pull (branch may contain / so we use variable)
clone_or_pull="if [ -d $BUILD_DIR/.git ]; then cd $BUILD_DIR && git fetch origin && git checkout $OPENCLAW_BRANCH 2>/dev/null || git checkout main && git pull origin $OPENCLAW_BRANCH 2>/dev/null || git pull; else rm -rf $BUILD_DIR && git clone --depth 1 -b $OPENCLAW_BRANCH $OPENCLAW_REPO_URL $BUILD_DIR && cd $BUILD_DIR; fi"
clone_or_pull_esc=$(escape_json "$clone_or_pull")

# On t3.small, pnpm install can OOM (exit 137). Ensure 2G swap before build.
ensure_swap="if [ ! -f /swapfile ] || ! grep -q /swapfile /proc/swaps 2>/dev/null; then sudo fallocate -l 2G /swapfile 2>/dev/null; sudo chmod 600 /swapfile; sudo mkswap /swapfile; sudo swapon /swapfile; grep -q /swapfile /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab; fi; echo \"Swap: \$(free -h | grep Swap)\""
ensure_swap_esc=$(escape_json "$ensure_swap")

params="{\"commands\":[
  \"set -e\",
  \"echo === Ensure swap (avoid OOM during pnpm install) ===\",
  \"$ensure_swap_esc\",
  \"echo === Clone or pull OpenClaw repo ===\",
  \"$clone_or_pull_esc\",
  \"cd $BUILD_DIR\",
  \"echo === Docker build openclaw:local ===\",
  \"sudo docker build --platform linux/amd64 -t openclaw:local .\",
  \"echo === Writing OpenClaw config ===\",
  \"$build_cfg_esc\",
  \"sudo chmod -R 777 $OPENCLAW_CONFIG_DIR\",
  \"sudo chmod -R 777 $OPENCLAW_HOME_DIR\",
  \"echo === Stop/remove container ===\",
  \"sudo docker stop openclaw 2>/dev/null || true\",
  \"sudo docker rm openclaw 2>/dev/null || true\",
  \"echo === Start container openclaw:local ===\",
  \"$run_cmd_esc\",
  \"sleep 4\",
  \"sudo docker ps -a --filter name=openclaw\",
  \"echo === Logs ===\",
  \"sudo docker logs openclaw --tail 40 2>&1\"
]}"

# SSM send-command: 2h timeout (t3.small full Docker build can take 1h+)
cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$params" \
  --timeout-seconds 7200 \
  --output text --query 'Command.CommandId')

echo "CommandId: $cmd_id"
echo "Build on LAB can take 30–90 min on t3.small. Waiting up to 2h..."
for i in $(seq 1 720); do
  status=$(aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'Status' --output text 2>/dev/null || echo "Pending")
  if [[ "$status" == "Success" ]]; then
    echo ""
    echo "=== Stdout ==="
    aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$LAB_INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query 'StandardOutputContent' --output text 2>/dev/null || true
    echo ""
    echo "=== Stderr ==="
    aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$LAB_INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query 'StandardErrorContent' --output text 2>/dev/null || true
    echo ""
    echo "==> Done. Run diagnostic: bash scripts/openclaw/run_gateway_model_diagnostic_via_ssm.sh"
    exit 0
  fi
  if [[ "$status" == "Failed" || "$status" == "Cancelled" || "$status" == "TimedOut" ]]; then
    echo ""
    echo "Status: $status"
    aws ssm get-command-invocation \
      --command-id "$cmd_id" \
      --instance-id "$LAB_INSTANCE_ID" \
      --region "$AWS_REGION" \
      --query '[Status,StandardOutputContent,StandardErrorContent]' --output text 2>/dev/null || true
    exit 1
  fi
  printf "."
  sleep 10
done
echo ""
echo "Timeout waiting for command. Check: aws ssm get-command-invocation --command-id $cmd_id --instance-id $LAB_INSTANCE_ID --region $AWS_REGION"
exit 1
