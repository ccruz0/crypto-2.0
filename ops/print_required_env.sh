#!/usr/bin/env bash
# Reprint the list of required env vars for ATP AWS profile (post-compromise rebuild).
# Run from repo root: ./ops/print_required_env.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

if [[ -f "$SCRIPT_DIR/inventory_env_vars.py" ]]; then
  exec python3 "$SCRIPT_DIR/inventory_env_vars.py"
fi
if [[ -x "$SCRIPT_DIR/inventory_env_vars.sh" ]]; then
  exec "$SCRIPT_DIR/inventory_env_vars.sh" "$ROOT"
fi
echo "Run: python3 $SCRIPT_DIR/inventory_env_vars.py" >&2
exit 1
