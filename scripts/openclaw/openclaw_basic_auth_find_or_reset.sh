#!/usr/bin/env bash
# Find or reset OpenClaw nginx Basic Auth, reload nginx, validate with curl.
# RUN ON THE DASHBOARD HOST (EC2) as ubuntu with sudo. Do not commit output containing the password.
#
# Usage:
#   ./scripts/openclaw/openclaw_basic_auth_find_or_reset.sh
#   OPENCLAW_BASIC_AUTH=openclaw:knownpass ./scripts/openclaw/openclaw_basic_auth_find_or_reset.sh   # skip reset, only validate
#
# Safety: backs up .htpasswd before change; does not modify nginx site config.
set -euo pipefail

HTPASSWD_FILE="${HTPASSWD_FILE:-/etc/nginx/.htpasswd_openclaw}"
USER_NAME="${OPENCLAW_HTUSER:-openclaw}"
VALIDATE_URL="${OPENCLAW_VALIDATE_URL:-https://dashboard.hilovivo.com/openclaw/}"
REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"

FOUND_SOURCE=""
FOUND_PASS=""

extract_pass_from_basic_auth() {
  # OPENCLAW_BASIC_AUTH=openclaw:secret or user:pass
  local v="$1"
  if [[ "$v" == *:* ]]; then
    local u="${v%%:*}"
    local p="${v#*:}"
    if [ "$u" = "$USER_NAME" ] && [ -n "$p" ]; then
      echo "$p"
      return 0
    fi
  fi
  return 1
}

try_env() {
  if [ -n "${OPENCLAW_BASIC_AUTH:-}" ]; then
    if p=$(extract_pass_from_basic_auth "$OPENCLAW_BASIC_AUTH"); then
      FOUND_SOURCE="environment OPENCLAW_BASIC_AUTH"
      FOUND_PASS="$p"
      return 0
    fi
  fi
  return 1
}

try_history() {
  local hf="${HOME}/.bash_history"
  [ -r "$hf" ] || return 1
  # Lines like: curl ... -u openclaw:secret or htpasswd ... openclaw secret
  while IFS= read -r line; do
    if [[ "$line" =~ -u[\ ]+${USER_NAME}:([^[:space:]\'\"]+) ]]; then
      FOUND_PASS="${BASH_REMATCH[1]}"
      FOUND_SOURCE="~/.bash_history (curl -u pattern)"
      return 0
    fi
  done < <(grep -E "openclaw|OPENCLAW_BASIC_AUTH|htpasswd.*openclaw" "$hf" 2>/dev/null | tail -50)
  return 1
}

try_repo_grep() {
  local row val p
  row=$(grep -hE "^OPENCLAW_BASIC_AUTH=${USER_NAME}:" \
    "$REPO_ROOT/.env" \
    "$REPO_ROOT/.env.local" \
    "$REPO_ROOT/secrets/runtime.env" \
    "$REPO_ROOT/.env.aws" 2>/dev/null | tail -1 || true)
  if [ -z "$row" ]; then
    return 1
  fi
  val="${row#*=}"
  val="${val%\"}"
  val="${val#\"}"
  val="${val%\'}"
  val="${val#\'}"
  if p=$(extract_pass_from_basic_auth "$val"); then
    FOUND_SOURCE="repo env file (OPENCLAW_BASIC_AUTH=...)"
    FOUND_PASS="$p"
    return 0
  fi
  return 1
}

validate_curl() {
  local pass="$1"
  local code
  code=$(curl -sS -o /dev/null -w "%{http_code}" -I -u "${USER_NAME}:${pass}" --max-time 15 "$VALIDATE_URL" || echo "000")
  echo "$code"
}

echo "=== OpenClaw Basic Auth: find or reset ==="
echo ""

if try_env; then
  echo "Found password from: $FOUND_SOURCE"
elif try_repo_grep; then
  echo "Found password from: $FOUND_SOURCE"
elif try_history; then
  echo "Found password from: $FOUND_SOURCE"
else
  echo "No existing password found in env, repo env files, or recent bash_history."
  FOUND_SOURCE="reset"
fi

if [ "$FOUND_SOURCE" != "reset" ] && [ -n "${FOUND_PASS:-}" ]; then
  code=$(validate_curl "$FOUND_PASS")
  if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ] || [ "$code" = "307" ] || [ "$code" = "308" ]; then
    echo ""
    echo "SUCCESS (existing password works)"
    echo "OpenClaw user: $USER_NAME"
    echo "OpenClaw password: $FOUND_PASS"
    echo "Test command:"
    echo "  curl -sS -I -u '${USER_NAME}:${FOUND_PASS}' '$VALIDATE_URL'"
    echo "HTTP status: $code"
    exit 0
  fi
  echo "Found credentials did not validate (HTTP $code). Proceeding to reset."
  FOUND_SOURCE="reset"
fi

# --- Reset ---
echo ""
echo "Resetting Basic Auth (backup htpasswd, then set new password)..."
NEW_PASS=$(openssl rand -base64 24 | tr -dc 'A-Za-z0-9' | head -c 20)
if [ ${#NEW_PASS} -lt 16 ]; then
  NEW_PASS=$(openssl rand -hex 16)
fi

if [ -f "$HTPASSWD_FILE" ]; then
  sudo cp -a "$HTPASSWD_FILE" "${HTPASSWD_FILE}.bak.$(date +%s)"
  echo "Backed up: ${HTPASSWD_FILE}.bak.*"
  sudo htpasswd -b "$HTPASSWD_FILE" "$USER_NAME" "$NEW_PASS"
else
  sudo htpasswd -b -c "$HTPASSWD_FILE" "$USER_NAME" "$NEW_PASS"
fi

sudo nginx -t
sudo systemctl reload nginx

code=$(validate_curl "$NEW_PASS")
echo ""
if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ] || [ "$code" = "307" ] || [ "$code" = "308" ]; then
  echo "SUCCESS (password reset)"
  echo "OpenClaw user: $USER_NAME"
  echo "OpenClaw password: $NEW_PASS"
  echo "Test command:"
  echo "  curl -sS -I -u '${USER_NAME}:${NEW_PASS}' '$VALIDATE_URL'"
  echo "HTTP status: $code"
  echo ""
  echo "Store this password in a password manager. Do not commit to git."
  echo "Optional (local only, never commit): echo 'OPENCLAW_BASIC_AUTH=${USER_NAME}:${NEW_PASS}' >> ~/.openclaw_basic_auth.env"
  echo "  and: chmod 600 ~/.openclaw_basic_auth.env"
  exit 0
fi

echo "FAIL: validation returned HTTP $code (expected 2xx or 3xx)"
echo "New password was set: $NEW_PASS"
echo ""
if [ "$code" = "503" ] || [ "$code" = "502" ] || [ "$code" = "504" ]; then
  echo "HTTP $code usually means nginx cannot reach OpenClaw (wrong proxy_pass IP/port, SG, or OpenClaw down)."
  echo "On this host test upstream (edit IP/port to match nginx dashboard.conf):"
  echo "  curl -sS -I --max-time 5 http://172.31.3.214:8081/   # LAB"
  echo "  curl -sS -I --max-time 5 http://127.0.0.1:8080/     # same-host OpenClaw"
fi
echo "URL: $VALIDATE_URL"
exit 1
