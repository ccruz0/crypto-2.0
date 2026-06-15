#!/usr/bin/env bash
# Resolve GIT_SHA/BUILD_TIME for docker compose build args and persist for later compose runs.
# Priority: existing GIT_SHA env (e.g. from GitHub Actions) -> .deploy-fingerprint.env -> ubuntu git rev-parse.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FINGERPRINT_FILE="$ROOT_DIR/.deploy-fingerprint.env"

if [[ -z "${GIT_SHA:-}" || "${GIT_SHA}" == "unknown" ]]; then
  if [[ -f "$FINGERPRINT_FILE" ]]; then
    # shellcheck disable=SC1090
    set -a
    # shellcheck source=/dev/null
    source "$FINGERPRINT_FILE"
    set +a
  fi
fi

if [[ -z "${GIT_SHA:-}" || "${GIT_SHA}" == "unknown" ]]; then
  if GIT_SHA="$(sudo -u ubuntu git -C "$ROOT_DIR" rev-parse HEAD 2>/dev/null)"; then
    :
  else
    GIT_SHA=""
  fi
fi

if [[ -z "${GIT_SHA:-}" || "${GIT_SHA}" == "unknown" ]]; then
  echo "ERROR: GIT_SHA is missing or unknown (set GIT_SHA env or ensure ubuntu-owned git checkout)" >&2
  exit 1
fi

BUILD_TIME="${BUILD_TIME:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"

umask 077
printf 'GIT_SHA=%s\nBUILD_TIME=%s\n' "$GIT_SHA" "$BUILD_TIME" >"$FINGERPRINT_FILE"
export GIT_SHA BUILD_TIME

echo "📌 Build fingerprint: GIT_SHA=$GIT_SHA BUILD_TIME=$BUILD_TIME"
echo "📁 Persisted compose env: $FINGERPRINT_FILE"
