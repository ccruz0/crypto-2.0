#!/usr/bin/env bash
# Install OpenClaw update daemon on LAB via SSM, then recreate the container.
# Usage: ./scripts/openclaw/install_openclaw_update_daemon_via_ssm.sh
#
# Requires: AWS credentials, LAB instance online, repo on main with the new files.
set -e

LAB_INSTANCE_ID="${LAB_INSTANCE_ID:-i-0d82c172235770a0d}"
AWS_REGION="${AWS_REGION:-ap-southeast-1}"
REPO_ON_LAB="${REPO_ON_LAB:-/home/ubuntu/automated-trading-platform}"

echo "=== Installing OpenClaw update daemon on LAB ($LAB_INSTANCE_ID) ==="

# Find repo and run (LAB may have automated-trading-platform or crypto-2.0)
# SSM runs as root; git needs safe.directory. Use ubuntu for git pull.
cmd1='REPO=; for d in /home/ubuntu/automated-trading-platform /home/ubuntu/crypto-2.0; do [ -f "$d/docker-compose.openclaw.yml" ] && REPO=$d && break; done; [ -d "$REPO" ] || { echo "Repo not found"; exit 1; }; cd "$REPO"'
cmd2='git config --global --add safe.directory "$(pwd)" 2>/dev/null || true; sudo -u ubuntu git -c safe.directory="$(pwd)" pull origin main 2>/dev/null || true'
cmd3='sudo bash scripts/openclaw/install_openclaw_update_daemon.sh'
cmd4='sudo docker stop openclaw 2>/dev/null || true; sudo docker rm openclaw 2>/dev/null || true; sudo docker compose -f docker-compose.openclaw.yml up -d'
cmd5='sleep 5; sudo systemctl status openclaw-update-daemon --no-pager'
cmd6='curl -s http://127.0.0.1:19999/health || echo health_check_failed'
# Escape for JSON: backslash and double-quote
params="{\"commands\":[\"set -e\",\"$(echo "$cmd1" | sed 's/\\/\\\\/g; s/"/\\"/g')\",\"$(echo "$cmd2" | sed 's/\\/\\\\/g; s/"/\\"/g')\",\"$(echo "$cmd3" | sed 's/\\/\\\\/g; s/"/\\"/g')\",\"$(echo "$cmd4" | sed 's/\\/\\\\/g; s/"/\\"/g')\",\"$(echo "$cmd5" | sed 's/\\/\\\\/g; s/"/\\"/g')\",\"$(echo "$cmd6" | sed 's/\\/\\\\/g; s/"/\\"/g')\"]}"

cmd_id=$(aws ssm send-command \
  --instance-ids "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --document-name "AWS-RunShellScript" \
  --parameters "$params" \
  --timeout-seconds 120 \
  --output text --query 'Command.CommandId')

echo "CommandId: $cmd_id"
echo "Waiting 90s for commands to complete..."
sleep 90

aws ssm get-command-invocation \
  --command-id "$cmd_id" \
  --instance-id "$LAB_INSTANCE_ID" \
  --region "$AWS_REGION" \
  --query '[Status, StandardOutputContent, StandardErrorContent]' --output text
