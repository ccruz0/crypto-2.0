#!/usr/bin/env bash
# Render runtime.env from SSM (on your Mac) and push to EC2 via SSM.
# EC2 has no AWS CLI, so render must run locally.
#
# Usage: ./scripts/aws/push_runtime_env_to_ec2.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

INSTANCE_ID="${ATP_INSTANCE_ID:-i-087953603011543c5}"
REGION="${AWS_REGION:-ap-southeast-1}"

echo "1) Rendering secrets/runtime.env..."
export AWS_DEFAULT_REGION="${AWS_REGION:-ap-southeast-1}"
REGION="${AWS_REGION:-ap-southeast-1}"

# Try full render first
if bash scripts/aws/render_runtime_env.sh 2>/dev/null; then
  echo "   Rendered from SSM."
else
  # Fallback: fetch token from SSM and merge into existing runtime.env
  echo "   Render failed; fetching TELEGRAM_BOT_TOKEN from SSM and merging..."
  TOKEN=$(aws ssm get-parameter --name /automated-trading-platform/prod/telegram/bot_token --with-decryption --query "Parameter.Value" --output text --region "$REGION" 2>/dev/null)
  if [[ -z "$TOKEN" ]]; then
    echo "ERROR: Could not get TELEGRAM_BOT_TOKEN from SSM."
    exit 1
  fi
  if [[ -f secrets/runtime.env ]]; then
    grep -v "^TELEGRAM_BOT_TOKEN=" secrets/runtime.env > secrets/runtime.env.tmp || true
    echo "TELEGRAM_BOT_TOKEN=$TOKEN" >> secrets/runtime.env.tmp
    mv secrets/runtime.env.tmp secrets/runtime.env
  else
    echo "ERROR: secrets/runtime.env not found. Run render or create it."
    exit 1
  fi
fi

echo ""
echo "2) Pushing to EC2 via SSM..."

python3 << PYSCRIPT
import json
import subprocess
import base64
import os

os.chdir("$ROOT_DIR")
with open("secrets/runtime.env", "rb") as f:
    b64_str = base64.b64encode(f.read()).decode().replace("\n", "")

if len(b64_str) > 3500:
    print("ERROR: runtime.env too large for SSM")
    exit(1)

# Two commands: 1) write file, 2) restart
cmd1 = f"echo '{b64_str}' | base64 -d > /home/ubuntu/crypto-2.0/secrets/runtime.env && chown ubuntu:ubuntu /home/ubuntu/crypto-2.0/secrets/runtime.env"
cmd2 = "sudo -u ubuntu bash -c 'cd /home/ubuntu/crypto-2.0 && docker compose --profile aws restart backend-aws backend-aws-canary'"
params = {"commands": [cmd1, cmd2]}

result = subprocess.run(
    ["aws", "ssm", "send-command",
     "--instance-ids", "$INSTANCE_ID",
     "--document-name", "AWS-RunShellScript",
     "--parameters", json.dumps(params),
     "--region", "$REGION",
     "--timeout-seconds", "120",
     "--output", "text", "--query", "Command.CommandId"],
    capture_output=True, text=True
)
print(result.stdout.strip() or result.stderr)
if result.returncode != 0:
    exit(1)
PYSCRIPT

echo ""
echo "3) Waiting 45s for restart..."
sleep 45

echo ""
echo "Done. Send /start in ATP Control to verify."
