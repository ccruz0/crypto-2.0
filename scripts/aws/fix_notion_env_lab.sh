#!/usr/bin/env bash
# Auto-repair Notion env on LAB: fetch from SSM, update .env.aws, rerender runtime.env, restart backend, verify.
# Run on the LAB host (no manual secrets). Requires LAB instance role ssm:GetParameter for
#   /automated-trading-platform/lab/notion/api_key
#
# Usage: ./scripts/aws/fix_notion_env_lab.sh
#        REPO_ROOT=/path ./scripts/aws/fix_notion_env_lab.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="${REPO_ROOT:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-ap-southeast-1}}"
SSM_LAB_KEY="/automated-trading-platform/lab/notion/api_key"
NOTION_TASK_DB_DEFAULT="eb90cfa139f94724a8b476315908510a"
ENV_AWS="$REPO_ROOT/.env.aws"

echo "fix_notion_env_lab: REPO_ROOT=$REPO_ROOT"

# 1) Fetch from LAB SSM (no user input)
NOTION_API_KEY_VAL=""
if command -v aws >/dev/null 2>&1; then
  NOTION_API_KEY_VAL="$(aws ssm get-parameter --name "$SSM_LAB_KEY" --with-decryption --query Parameter.Value --output text --region "$REGION" 2>/dev/null)" || true
fi

if [[ -z "$NOTION_API_KEY_VAL" ]]; then
  echo "ERROR: Could not read Notion API key from SSM: $SSM_LAB_KEY" >&2
  echo "Ensure the parameter exists and this host's role has ssm:GetParameter. No secrets requested." >&2
  echo "Create parameter (from a machine with AWS CLI): see scripts/aws/store_lab_notion_api_key_ssm.sh" >&2
  exit 1
fi

# 2) Update .env.aws safely (upsert NOTION_API_KEY and NOTION_TASK_DB)
mkdir -p "$(dirname "$ENV_AWS")"
touch "$ENV_AWS"
if grep -q '^NOTION_API_KEY=' "$ENV_AWS" 2>/dev/null; then
  sed -i.bak "s|^NOTION_API_KEY=.*|NOTION_API_KEY=$NOTION_API_KEY_VAL|" "$ENV_AWS"
else
  printf "\nNOTION_API_KEY=%s\n" "$NOTION_API_KEY_VAL" >> "$ENV_AWS"
fi
if grep -q '^NOTION_TASK_DB=' "$ENV_AWS" 2>/dev/null; then
  sed -i.bak "s|^NOTION_TASK_DB=.*|NOTION_TASK_DB=$NOTION_TASK_DB_DEFAULT|" "$ENV_AWS"
else
  printf "NOTION_TASK_DB=%s\n" "$NOTION_TASK_DB_DEFAULT" >> "$ENV_AWS"
fi
rm -f "${ENV_AWS}.bak"
echo "Updated .env.aws (NOTION_API_KEY and NOTION_TASK_DB)."

# 3) Rerender runtime.env (will pick up from .env.aws and/or LAB SSM)
cd "$REPO_ROOT"
bash scripts/aws/render_runtime_env.sh
echo "Rendered secrets/runtime.env"

# 4) Restart backend-aws so it loads new env
cd "$REPO_ROOT"
docker compose --profile aws up -d backend-aws
echo "Restarted backend-aws; waiting 15s..."
sleep 15

# 5) Verify env inside container (do not print values)
KEY_PRESENT="$(docker compose --profile aws exec -T backend-aws sh -c 'test -n "$NOTION_API_KEY" && echo present || echo missing' 2>/dev/null)" || echo "missing"
DB_PRESENT="$(docker compose --profile aws exec -T backend-aws sh -c 'test -n "$NOTION_TASK_DB" && echo present || echo missing' 2>/dev/null)" || echo "missing"
echo "Container NOTION_API_KEY: $KEY_PRESENT"
echo "Container NOTION_TASK_DB: $DB_PRESENT"

if [[ "$KEY_PRESENT" != "present" || "$DB_PRESENT" != "present" ]]; then
  echo "WARN: Notion env still missing in container. Run: ./scripts/diagnostics/check_notion_env.sh" >&2
  exit 1
fi
echo "fix_notion_env_lab: done. Run ./scripts/run_notion_task_pickup.sh to run one pickup cycle."
