#!/usr/bin/env bash
# Create deploy-in-progress marker, run a command, remove marker on exit (success or failure).
# Used by deploy workflows so self-heal skips recovery during deploys.
set -euo pipefail

MARKER="${ATP_DEPLOY_MARKER:-/tmp/atp-deploy-in-progress}"

if [ $# -lt 1 ]; then
  echo "Usage: $0 <command> [args...]" >&2
  exit 2
fi

cleanup() {
  rm -f "$MARKER"
}

trap cleanup EXIT INT TERM
echo "deploy started $(date -Is) pid=$$" >"$MARKER"
exec "$@"
