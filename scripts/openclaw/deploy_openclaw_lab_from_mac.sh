#!/usr/bin/env bash
# Deploy OpenClaw on LAB from your Mac (build wrapper, push to GHCR, run on LAB via SSM).
# Usage:
#   ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh              # full: build wrapper, push, deploy on LAB
#   ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh build         # only build wrapper image
#   ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh push         # only push to GHCR
#   ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh deploy       # only run on LAB via SSM
#   ./scripts/openclaw/deploy_openclaw_lab_from_mac.sh logs         # get logs from LAB via SSM
set -e

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
OPENCLAW_IMAGE="${OPENCLAW_IMAGE:-ghcr.io/ccruz0/openclaw:latest}"
OPENCLAW_IMAGE_FALLBACK="${OPENCLAW_IMAGE_FALLBACK:-ghcr.io/ccruz0/openclaw:latest}"
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
OPENCLAW_ALLOWED_ORIGINS="${OPENCLAW_ALLOWED_ORIGINS:-https://dashboard.hilovivo.com,http://localhost:18789,http://127.0.0.1:18789}"
OPENCLAW_CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/opt/openclaw}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_CONFIG_DIR/openclaw.json}"
ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}"
OPENAI_API_KEY="${OPENAI_API_KEY:-}"
OPENCLAW_HOME_DIR="${OPENCLAW_HOME_DIR:-/opt/openclaw/home-data}"
ATP_REPO_PATH="${ATP_REPO_PATH:-/home/ubuntu/crypto-2.0}"
OPENCLAW_TRUSTED_PROXIES="${OPENCLAW_TRUSTED_PROXIES:-172.31.32.169}"
OPENCLAW_MODEL_PRIMARY="${OPENCLAW_MODEL_PRIMARY:-openai/gpt-4o-mini}"
OPENCLAW_MODEL_FALLBACKS="${OPENCLAW_MODEL_FALLBACKS:-anthropic/claude-3-5-haiku-20241022,anthropic/claude-3-5-sonnet-20241022,openai/gpt-4o,anthropic/claude-sonnet-4-20250514}"
OPENCLAW_ACP_DEFAULT_AGENT="${OPENCLAW_ACP_DEFAULT_AGENT:-codex}"

do_build() {
  echo "==> Building wrapper image (openclaw-with-origins:latest) for linux/amd64"
  cd "$REPO_ROOT"
  docker build --platform linux/amd64 -f openclaw/Dockerfile.openclaw -t openclaw-with-origins:latest .
  docker tag openclaw-with-origins:latest "$OPENCLAW_IMAGE"
}

do_push() {
  echo "==> Pushing to GHCR ($OPENCLAW_IMAGE)"
  docker push "$OPENCLAW_IMAGE" || {
    echo "Push failed. Log in with: docker login ghcr.io -u ccruz0"
    exit 1
  }
}

do_deploy() {
  echo "==> Deploying on LAB ($LAB_INSTANCE_ID) via SSM"
  # Build JSON array of commands (escape backslash and double-quote in values)
  model_env_flags=""
  if [[ -n "$ANTHROPIC_API_KEY" ]]; then
    model_env_flags="$model_env_flags -e ANTHROPIC_API_KEY=$(printf '%q' "$ANTHROPIC_API_KEY")"
  fi
  if [[ -n "$OPENAI_API_KEY" ]]; then
    model_env_flags="$model_env_flags -e OPENAI_API_KEY=$(printf '%q' "$OPENAI_API_KEY")"
  fi
  # Write provider API keys into OpenClaw persistent home so the agent subprocess finds them.
  write_provider_env="sudo mkdir -p $OPENCLAW_HOME_DIR && sudo python3 -c 'import os, pathlib; env_path=pathlib.Path(\"$OPENCLAW_HOME_DIR/.env\"); existing=env_path.read_text() if env_path.exists() else \"\"; lines={l.split(\"=\",1)[0]:l for l in existing.splitlines() if \"=\" in l}; "
  if [[ -n "$ANTHROPIC_API_KEY" ]]; then
    write_provider_env="${write_provider_env}lines[\"ANTHROPIC_API_KEY\"]=\"ANTHROPIC_API_KEY=$(printf '%q' "$ANTHROPIC_API_KEY")\"; "
  fi
  if [[ -n "$OPENAI_API_KEY" ]]; then
    write_provider_env="${write_provider_env}lines[\"OPENAI_API_KEY\"]=\"OPENAI_API_KEY=$(printf '%q' "$OPENAI_API_KEY")\"; "
  fi
  write_provider_env="${write_provider_env}env_path.write_text(chr(10).join(lines.values())+chr(10)); print(\"Provider keys written to \"+str(env_path))'"

  # Write config to home-data (gateway reads ~/.openclaw/openclaw.json = OPENCLAW_HOME_DIR). Match docker-compose path.
  OPENCLAW_CONFIG_IN_CONTAINER="/home/node/.openclaw/openclaw.json"
  build_cfg="OPENCLAW_ALLOWED_ORIGINS=$OPENCLAW_ALLOWED_ORIGINS OPENCLAW_TRUSTED_PROXIES=$OPENCLAW_TRUSTED_PROXIES OPENCLAW_MODEL_PRIMARY=$OPENCLAW_MODEL_PRIMARY OPENCLAW_MODEL_FALLBACKS=$OPENCLAW_MODEL_FALLBACKS OPENCLAW_ACP_DEFAULT_AGENT=$OPENCLAW_ACP_DEFAULT_AGENT OPENCLAW_HOME_DIR=$OPENCLAW_HOME_DIR python3 -c 'import json, os, pathlib, secrets; origins=[s.strip() for s in os.environ.get(\"OPENCLAW_ALLOWED_ORIGINS\", \"\").split(\",\") if s.strip()]; proxies=[s.strip() for s in os.environ.get(\"OPENCLAW_TRUSTED_PROXIES\", \"\").split(\",\") if s.strip()]; primary=os.environ.get(\"OPENCLAW_MODEL_PRIMARY\", \"openai/gpt-4o-mini\").strip(); fallbacks=[f.strip() for f in os.environ.get(\"OPENCLAW_MODEL_FALLBACKS\", \"\").split(\",\") if f.strip()]; acp_agent=os.environ.get(\"OPENCLAW_ACP_DEFAULT_AGENT\", \"codex\").strip(); p=pathlib.Path(os.environ[\"OPENCLAW_HOME_DIR\"])/\"openclaw.json\"; p.parent.mkdir(parents=True, exist_ok=True); cfg={}; exists=p.exists(); cfg=(json.loads(p.read_text()) if exists else {}); gateway=cfg.setdefault(\"gateway\", {}); control_ui=gateway.setdefault(\"controlUi\", {}); control_ui[\"allowedOrigins\"]=origins; gateway[\"trustedProxies\"]=proxies if proxies else gateway.get(\"trustedProxies\", []); auth=gateway.setdefault(\"auth\", {}); token=(auth.get(\"token\") or \"\").strip(); token=(token or os.environ.get(\"OPENCLAW_GATEWAY_TOKEN\", \"\").strip() or secrets.token_hex(24)); auth[\"token\"]=token; agents=cfg.setdefault(\"agents\", {}); defaults=agents.setdefault(\"defaults\", {}); defaults[\"model\"]={\"primary\": primary, \"fallbacks\": fallbacks}; acp=cfg.setdefault(\"acp\", {}); acp[\"defaultAgent\"]=acp_agent; p.write_text(json.dumps(cfg), encoding=\"utf-8\"); print(\"OPENCLAW_GATEWAY_TOKEN=\"+token)'"
  # Host port must match PROD nginx proxy_pass (default 8080). Config path matches docker-compose: /home/node/.openclaw/openclaw.json
  # -v /var/run/docker.sock and --group-add: tools can run docker ps/logs without sudo (see OPENCLAW_DOCKER_SOCKET.md)
  DOCKER_GID="${DOCKER_GROUP_GID:-988}"
  run1="sudo docker run -d --restart unless-stopped -p 8080:18789 --group-add $DOCKER_GID -v /var/run/docker.sock:/var/run/docker.sock -e OPENCLAW_ALLOWED_ORIGINS=$OPENCLAW_ALLOWED_ORIGINS -e OPENCLAW_TRUSTED_PROXIES=$OPENCLAW_TRUSTED_PROXIES -e OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_IN_CONTAINER$model_env_flags -v $OPENCLAW_HOME_DIR:/home/node/.openclaw -v $ATP_REPO_PATH:/home/node/.openclaw/workspace/atp:ro -v $OPENCLAW_HOME_DIR/agents:/home/node/openclaw/agents --name openclaw $OPENCLAW_IMAGE"
  run2="sudo docker run -d --restart unless-stopped -p 8080:18789 --group-add $DOCKER_GID -v /var/run/docker.sock:/var/run/docker.sock -e OPENCLAW_ALLOWED_ORIGINS=$OPENCLAW_ALLOWED_ORIGINS -e OPENCLAW_TRUSTED_PROXIES=$OPENCLAW_TRUSTED_PROXIES -e OPENCLAW_CONFIG_PATH=$OPENCLAW_CONFIG_IN_CONTAINER$model_env_flags -v $OPENCLAW_HOME_DIR:/home/node/.openclaw -v $ATP_REPO_PATH:/home/node/.openclaw/workspace/atp:ro -v $OPENCLAW_HOME_DIR/agents:/home/node/openclaw/agents --name openclaw $OPENCLAW_IMAGE_FALLBACK"
  write_env_esc=$(echo "$write_provider_env" | sed 's/\\/\\\\/g; s/"/\\"/g')
  build_cfg_esc=$(echo "$build_cfg" | sed 's/\\/\\\\/g; s/"/\\"/g')
  run1_esc=$(echo "$run1" | sed 's/\\/\\\\/g; s/"/\\"/g')
  run2_esc=$(echo "$run2" | sed 's/\\/\\\\/g; s/"/\\"/g')
  pull_esc="sudo docker pull $OPENCLAW_IMAGE || sudo docker pull $OPENCLAW_IMAGE_FALLBACK"
  pull_esc=$(echo "$pull_esc" | sed 's/\\/\\\\/g; s/"/\\"/g')
  run_both_esc="${run1_esc} || ${run2_esc}"
  params="{\"commands\":[\"set -e\",\"echo === Pulling image ===\",\"$pull_esc\",\"echo === Writing provider keys ===\",\"$write_env_esc\",\"echo === Writing OpenClaw config ===\",\"$build_cfg_esc\",\"sudo chmod -R 777 $OPENCLAW_CONFIG_DIR\",\"sudo chmod -R 777 $OPENCLAW_HOME_DIR\",\"echo === Stop/remove container ===\",\"sudo docker stop openclaw 2>/dev/null || true\",\"sudo docker rm openclaw 2>/dev/null || true\",\"echo === Start container ===\",\"$run_both_esc\",\"sleep 4\",\"sudo docker ps -a --filter name=openclaw\",\"echo === Logs ===\",\"sudo docker logs openclaw --tail 60 2>&1\"]}"
  cmd_id=$(aws ssm send-command \
    --instance-ids "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters "$params" \
    --output text --query 'Command.CommandId')
  echo "CommandId: $cmd_id"
  echo "Waiting 50s for command to complete..."
  sleep 50
  aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query '[Status, StandardOutputContent]' --output text
}

do_logs() {
  echo "==> Fetching logs from LAB ($LAB_INSTANCE_ID)"
  cmd_id=$(aws ssm send-command \
    --instance-ids "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --document-name "AWS-RunShellScript" \
    --parameters 'commands=["sudo docker logs openclaw --tail 120 2>&1"]' \
    --output text --query 'Command.CommandId')
  sleep 15
  aws ssm get-command-invocation \
    --command-id "$cmd_id" \
    --instance-id "$LAB_INSTANCE_ID" \
    --region "$AWS_REGION" \
    --query 'StandardOutputContent' --output text
}

case "${1:-}" in
  build)  do_build ;;
  push)   do_push ;;
  deploy) do_deploy ;;
  logs)   do_logs ;;
  "")
    do_build
    do_push
    do_deploy
    echo ""
    echo "==> To see logs later: $0 logs"
    ;;
  *)
    echo "Usage: $0 [build|push|deploy|logs]"
    echo "  (no arg = build + push + deploy)"
    exit 1
    ;;
esac
