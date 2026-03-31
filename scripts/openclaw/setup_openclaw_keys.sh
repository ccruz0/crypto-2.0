#!/usr/bin/env bash
# Securely store OpenClaw provider keys, sync auth-profiles.json, recreate container, validate gateway.
# Usage: bash scripts/openclaw/setup_openclaw_keys.sh
# Validation URL port: OPENCLAW_GATEWAY_PORT or OPENCLAW_HOST_PORT (compose), default 18790.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
SYNC_SCRIPT="$SCRIPT_DIR/sync_openclaw_auth_profiles.sh"
COMPOSE_FILE="$REPO_ROOT/docker-compose.openclaw.yml"

HOME_DATA="/opt/openclaw/home-data"
ENV_FILE="$HOME_DATA/.env"
CONFIG_JSON="$HOME_DATA/openclaw.json"
GATEWAY_PORT="${OPENCLAW_GATEWAY_PORT:-${OPENCLAW_HOST_PORT:-18790}}"
GATEWAY_URL="http://127.0.0.1:${GATEWAY_PORT}/v1/responses"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

echo "==> Step 1: Secure key input (nothing you type is echoed)"
printf '%s' "OPENAI_API_KEY (required): "
read -rs OPENAI_KEY
echo
printf '%s' "ANTHROPIC_API_KEY (optional, Enter to skip): "
read -rs ANTHROPIC_KEY
echo

# Trim surrounding whitespace; strip newlines from pasted input (keys must be single-line).
OPENAI_KEY="${OPENAI_KEY#"${OPENAI_KEY%%[![:space:]]*}"}"
OPENAI_KEY="${OPENAI_KEY%"${OPENAI_KEY##*[![:space:]]}"}"
OPENAI_KEY="${OPENAI_KEY//$'\r'/}"
OPENAI_KEY="${OPENAI_KEY//$'\n'/}"
ANTHROPIC_KEY="${ANTHROPIC_KEY#"${ANTHROPIC_KEY%%[![:space:]]*}"}"
ANTHROPIC_KEY="${ANTHROPIC_KEY%"${ANTHROPIC_KEY##*[![:space:]]}"}"
ANTHROPIC_KEY="${ANTHROPIC_KEY//$'\r'/}"
ANTHROPIC_KEY="${ANTHROPIC_KEY//$'\n'/}"

[[ -n "$OPENAI_KEY" ]] || die "OPENAI_API_KEY is required (empty after trim)."

echo "==> Step 2: Write $ENV_FILE (atomic, root-owned 600, uid 1000)"
sudo mkdir -p "$HOME_DATA"
tmp_env="$(mktemp)"
chmod 600 "$tmp_env"
{
  printf '%s\n' "OPENAI_API_KEY=${OPENAI_KEY}"
  if [[ -n "$ANTHROPIC_KEY" ]]; then
    printf '%s\n' "ANTHROPIC_API_KEY=${ANTHROPIC_KEY}"
  fi
} >"$tmp_env"
sudo install -m 600 -o 1000 -g 1000 "$tmp_env" "$ENV_FILE"
rm -f "$tmp_env"

unset OPENAI_KEY ANTHROPIC_KEY

echo "==> Step 3: Sync auth-profiles.json (ignore stale lab key cache)"
export OPENCLAW_KEY_CACHE_FILE=/dev/null
bash "$SYNC_SCRIPT"

echo "==> Step 4: Recreate OpenClaw container"
cd "$REPO_ROOT"
docker compose -f "$COMPOSE_FILE" up -d --force-recreate openclaw

echo "==> Step 5: Validate gateway /v1/responses"
command -v jq >/dev/null 2>&1 || die "jq is required for gateway token extraction."
[[ -r "$CONFIG_JSON" ]] || die "Cannot read $CONFIG_JSON"
TOKEN="$(jq -r '.gateway.auth.token // empty' "$CONFIG_JSON")"
[[ -n "$TOKEN" ]] || die "gateway.auth.token missing in $CONFIG_JSON"

tmp_body="$(mktemp)"
chmod 600 "$tmp_body"
HTTP_CODE="$(
  curl -sS -o "$tmp_body" -w '%{http_code}' \
    -X POST "$GATEWAY_URL" \
    -H "Authorization: Bearer ${TOKEN}" \
    -H "Content-Type: application/json" \
    -d '{"model":"openai/gpt-4o-mini","input":"Say only: ok"}' || true
)"
BODY="$(cat "$tmp_body")"
rm -f "$tmp_body"

echo "HTTP code: $HTTP_CODE"
echo "Response body:"
echo "$BODY"

echo "==> Step 6: Result"
if [[ "$HTTP_CODE" == "200" ]] && [[ "$BODY" == *"ok"* ]]; then
  echo "OpenClaw setup SUCCESS"
  exit 0
fi

echo "OpenClaw setup FAILED" >&2
echo "---- Last 20 lines: docker logs openclaw ----" >&2
docker logs openclaw --tail 20 >&2 || true
exit 1
