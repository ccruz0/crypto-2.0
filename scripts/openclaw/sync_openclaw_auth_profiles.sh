#!/usr/bin/env bash
# Sync OpenClaw main agent auth store from OPENAI_API_KEY / ANTHROPIC_API_KEY
# (environment and/or /opt/openclaw/home-data/.env). See write_openclaw_auth_profiles.py.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
export OPENCLAW_HOME_DATA="${OPENCLAW_HOME_DATA:-/opt/openclaw/home-data}"
export OPENCLAW_HOME_DIR="${OPENCLAW_HOME_DIR:-$OPENCLAW_HOME_DATA}"

CACHE_FILE="${OPENCLAW_KEY_CACHE_FILE:-$HOME/.openclaw/lab-provider-keys.env}"

# Optional: keys from popup deploy cache (Python also reads $OPENCLAW_HOME_DIR/.env).
# shellcheck disable=SC1090
[[ -f "$CACHE_FILE" ]] && set -a && source "$CACHE_FILE" && set +a || true

# sudo resets the environment; use env(1) so provider keys reach the writer.
sudo env OPENCLAW_HOME_DIR="$OPENCLAW_HOME_DIR" \
  OPENAI_API_KEY="${OPENAI_API_KEY:-}" ANTHROPIC_API_KEY="${ANTHROPIC_API_KEY:-}" \
  python3 "$REPO_ROOT/scripts/openclaw/write_openclaw_auth_profiles.py"
sudo chown -R 1000:1000 "$OPENCLAW_HOME_DIR"
AUTH_JSON="$OPENCLAW_HOME_DIR/agents/main/agent/auth-profiles.json"
[[ -f "$AUTH_JSON" ]] && sudo chmod 600 "$AUTH_JSON"
