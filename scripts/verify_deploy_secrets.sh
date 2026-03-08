#!/usr/bin/env bash
# Verify deploy secrets are loaded in the running backend-aws container.
# Reports presence only (never values). Use after deploy to confirm GITHUB_TOKEN is available.
#
# Usage:
#   ./scripts/verify_deploy_secrets.sh
#   # On EC2 via SSM:
#   aws ssm send-command --instance-ids i-xxx --document-name AWS-RunShellScript \
#     --parameters 'commands=["cd ~/automated-trading-platform && ./scripts/verify_deploy_secrets.sh"]' ...

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$SCRIPT_DIR/.."
cd "$ROOT_DIR"

CONTAINER="$(docker ps -q --filter 'name=backend-aws' | head -1)"
if [[ -z "$CONTAINER" ]]; then
  echo "ERROR: backend-aws container not running" >&2
  exit 1
fi

echo "== Deploy secrets (container env, presence only) =="
docker exec "$CONTAINER" python3 - <<'PY'
import os
def present(name):
    return "yes" if bool((os.getenv(name) or "").strip()) else "no"

keys = [
    ("GITHUB_TOKEN", "required for deploy trigger from Telegram"),
    ("GITHUB_WEBHOOK_SECRET", "optional, for webhook signature verification"),
    ("OPENCLAW_API_TOKEN", "optional, for OpenClaw integration"),
]
for key, desc in keys:
    p = present(key)
    status = "OK" if (key == "GITHUB_TOKEN" and p == "yes") or (key != "GITHUB_TOKEN") else "MISSING"
    print(f"  {key}: {p} ({desc})")
    if key == "GITHUB_TOKEN" and p == "no":
        print("  ^^^ DEPLOY AUTOMATION NOT READY - Telegram deploy approval will fail")
PY

echo
echo "== Deploy automation ready? =="
GITHUB_PRESENT=$(docker exec "$CONTAINER" python3 -c "import os; print('yes' if (os.getenv('GITHUB_TOKEN') or '').strip() else 'no')")
if [[ "$GITHUB_PRESENT" == "yes" ]]; then
  echo "  YES - GITHUB_TOKEN is set; deploy trigger from Telegram will work"
  exit 0
else
  echo "  NO - GITHUB_TOKEN missing. Run: bash scripts/aws/render_runtime_env.sh"
  echo "  Then: docker compose --profile aws up -d --force-recreate backend-aws"
  exit 1
fi
