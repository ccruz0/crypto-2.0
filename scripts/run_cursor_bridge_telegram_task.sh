#!/usr/bin/env bash
# Run Cursor Bridge for Telegram task 4d7d1312 (investigate alerts not sent)
# Uses backend venv which has httpx and other deps.

set -e
cd "$(dirname "$0")/.."
BACKEND_PY="${BACKEND_PY:-backend/.venv/bin/python}"
if [[ ! -x "$BACKEND_PY" ]]; then
  echo "Backend venv not found at $BACKEND_PY. Run: cd backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt"
  exit 1
fi

export ATP_WORKSPACE_ROOT="$(pwd)"
export CURSOR_BRIDGE_ENABLED=true

# If cursor not in PATH, try Mac default (Cmd+Shift+P > "Install cursor command" to add to PATH)
if ! command -v cursor &>/dev/null; then
  MAC_CURSOR="/Applications/Cursor.app/Contents/Resources/app/bin/cursor"
  if [[ -x "$MAC_CURSOR" ]]; then
    export CURSOR_CLI_PATH="$MAC_CURSOR"
    echo "Using cursor at $MAC_CURSOR"
  else
    echo "cursor CLI not found. In Cursor IDE: Cmd+Shift+P -> 'Install cursor command in PATH'"
    exit 1
  fi
fi

"$BACKEND_PY" -c "
import sys
sys.path.insert(0, 'backend')
from app.services.cursor_execution_bridge import is_bridge_enabled, run_bridge_phase2
print('Bridge enabled:', is_bridge_enabled())
r = run_bridge_phase2(task_id='4d7d1312-8ece-4fcb-b092-ef437c09ee2c', ingest=True, create_pr=False)
print('Result:', r)
"
