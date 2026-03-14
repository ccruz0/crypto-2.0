#!/usr/bin/env bash
# Append OpenClaw task-type routing vars to secrets/runtime.env.
# Run after render_runtime_env.sh or when runtime.env already exists.
# Safe to run multiple times (idempotent: skips if vars already present).

set -e
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_ENV="$REPO_ROOT/secrets/runtime.env"

if [[ ! -f "$RUNTIME_ENV" ]]; then
  echo "ERROR: secrets/runtime.env not found. Run scripts/aws/render_runtime_env.sh first." >&2
  exit 1
fi

append_if_missing() {
  local name="$1"
  local value="$2"
  if ! grep -q "^${name}=" "$RUNTIME_ENV" 2>/dev/null; then
    echo "${name}=${value}" >> "$RUNTIME_ENV"
    echo "Appended ${name}"
  else
    echo "Already present: ${name}"
  fi
}

echo "=== Appending OpenClaw task-type routing to $RUNTIME_ENV ==="
append_if_missing "OPENCLAW_CHEAP_TASK_TYPES" "doc,documentation,monitoring,triage"
append_if_missing "OPENCLAW_CHEAP_MODEL_CHAIN" "openai/gpt-4o-mini"
echo "Done. Restart backend to pick up changes."
