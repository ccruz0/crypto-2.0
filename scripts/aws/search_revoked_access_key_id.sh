#!/usr/bin/env bash
# Phase D helper — list local files that contain a revoked AWS access-key ID.
# Prints matching paths only. Does not delete anything. Does not print the key.
#
# Run on the operator Mac with bash (not a zsh paste of a for-loop):
#   export REVOKED_AWS_ACCESS_KEY_ID='AKIA...'   # access-key ID only; do not commit
#   bash scripts/aws/search_revoked_access_key_id.sh
set -euo pipefail
export LC_ALL=C

KEY="${REVOKED_AWS_ACCESS_KEY_ID:-}"
if [[ -z "$KEY" ]]; then
  echo "FAIL: export REVOKED_AWS_ACCESS_KEY_ID to the revoked access-key ID first." >&2
  echo "Do not commit that value. Paste it only in the terminal." >&2
  exit 1
fi
# AWS access-key IDs are AKIA + 16 alphanumeric chars. Reject placeholders
# such as AKIA...paste-the-id...
if [[ ! "$KEY" =~ ^AKIA[A-Z0-9]{16}$ ]]; then
  echo "FAIL: REVOKED_AWS_ACCESS_KEY_ID must be a 20-character AKIA id, not a placeholder." >&2
  exit 1
fi

hits=0

search_dir() {
  local d="$1"
  if [[ ! -d "$d" ]]; then
    echo "skip missing ${d}"
    return 0
  fi
  echo "=== ${d} ==="
  local found
  found="$(grep -R -l --binary-files=without-match -- "$KEY" "$d" 2>/dev/null || true)"
  if [[ -n "$found" ]]; then
    printf '%s\n' "$found"
    hits=$((hits + $(printf '%s\n' "$found" | grep -c . || true)))
  else
    echo "(no matches)"
  fi
}

search_dir "${HOME}/.aws"
search_dir "${HOME}/automated-trading-platform"
search_dir "${HOME}/crypto-2.0"
search_dir "${HOME}/aws-rollback-legacy-cleanup-20260606"
search_dir "${HOME}/atp-lab-builder"
search_dir "${HOME}/imap-teams"
search_dir "/tmp/atp-iam"

echo "=== env-like files under ${HOME} (Library Music .Trash .cache pruned) ==="
env_hits=0
while IFS= read -r -d '' f; do
  if grep -q --binary-files=without-match -- "$KEY" "$f" 2>/dev/null; then
    echo "$f"
    env_hits=$((env_hits + 1))
    hits=$((hits + 1))
  fi
done < <(find "$HOME" \
  \( -path "$HOME/Library" -o -path "$HOME/Music" -o -path "$HOME/.Trash" \
     -o -path "$HOME/.cache" -o -path "$HOME/node_modules" \) -prune -o \
  \( -name '.env' -o -name '.env.*' -o -name '*.env' -o -name 'credentials' \
     -o -name 'credentials.bak' -o -name '*.bak' \) -type f -print0 2>/dev/null || true)

if [[ "$env_hits" -eq 0 ]]; then
  echo "(no matches)"
fi

echo "=== done hits=${hits} ==="
echo "List only. Confirm each path before deleting. After LAB instance-role cutover, jarvis-lab-bedrock user keys can be deactivated."
