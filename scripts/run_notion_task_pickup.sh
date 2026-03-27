#!/usr/bin/env bash
# Run Notion connection check and one agent scheduler cycle so a Planned task gets picked.
# Use on the host where the backend runs (e.g. EC2) or in a venv that has backend deps.
#
# On AWS (backend in Docker):
#   cd /home/ubuntu/crypto-2.0
#   ./scripts/run_notion_task_pickup.sh
#
# When run on the server, the script passes NOTION_TASK_DB into the container for this run,
# so you can run it once without restarting the backend. For the scheduler to keep picking
# tasks every 5 min, add NOTION_TASK_DB=eb90cfa139f94724a8b476315908510a to secrets/runtime.env
# and restart backend-aws.

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

NOTION_TASK_DB="${NOTION_TASK_DB:-eb90cfa139f94724a8b476315908510a}"

echo "=== Notion task pickup ==="
echo "NOTION_TASK_DB=$NOTION_TASK_DB"
echo ""

# If we're in a context where docker compose is available and backend-aws is running, run inside container
if command -v docker >/dev/null 2>&1 && docker compose --profile aws ps backend-aws 2>/dev/null | grep -q Up; then
  echo "Running Notion check inside backend-aws container..."
  [[ -n "${TASK_ID:-}" ]] && echo "Target task: $TASK_ID"
  docker compose --profile aws exec -e NOTION_TASK_DB="$NOTION_TASK_DB" -e TASK_ID="${TASK_ID:-}" backend-aws python -c "
import os
os.environ.setdefault('NOTION_TASK_DB', os.environ.get('NOTION_TASK_DB', ''))
from app.services.agent_scheduler import run_agent_scheduler_cycle
import json
import os
task_id = (os.environ.get('TASK_ID') or '').strip() or None
result = run_agent_scheduler_cycle(task_id=task_id)
print(json.dumps(result, default=str, indent=2))
" 2>&1
  echo ""
  echo "Done. Check Notion: task should be In Progress or Investigation Complete, and Telegram may have an approval."
  exit 0
fi

# Otherwise run locally (requires NOTION_API_KEY and NOTION_TASK_DB in env or backend/.env)
echo "Docker backend-aws not detected. Running scheduler cycle locally (backend/ must have NOTION_API_KEY and NOTION_TASK_DB)..."
export NOTION_TASK_DB
export TASK_ID="${TASK_ID:-}"
cd "$REPO_ROOT/backend"
# Load env files so NOTION_API_KEY and Telegram (encrypted token + chat_id) are available.
# Order: root .env, then runtime.env, then backend/.env so local backend/.env overrides (e.g. TELEGRAM_BOT_TOKEN_ENCRYPTED from setup_telegram_token.py).
if [ -f "$REPO_ROOT/.env" ]; then set -a; source "$REPO_ROOT/.env" 2>/dev/null; set +a; fi
if [ -f "$REPO_ROOT/secrets/runtime.env" ]; then set -a; source "$REPO_ROOT/secrets/runtime.env" 2>/dev/null; set +a; fi
if [ -f ".env" ]; then set -a; source .env 2>/dev/null; set +a; fi
# So backend can decrypt TELEGRAM_BOT_TOKEN_ENCRYPTED when running locally
if [ -f "$REPO_ROOT/secrets/telegram_key" ]; then export TELEGRAM_KEY_FILE="$REPO_ROOT/secrets/telegram_key"; fi
if [ -f "$REPO_ROOT/.telegram_key" ]; then export TELEGRAM_KEY_FILE="$REPO_ROOT/.telegram_key"; fi
if [ -x ".venv/bin/python" ]; then
  PYTHONPATH=. .venv/bin/python scripts/run_agent_scheduler_cycle.py 2>&1
else
  python scripts/run_agent_scheduler_cycle.py 2>&1
fi
echo ""
echo "Done. Check Notion and Telegram."
