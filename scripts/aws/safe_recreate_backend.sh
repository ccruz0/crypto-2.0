#!/usr/bin/env bash
# Safely recreate backend-aws (+ canary) after an env-var change (e.g. editing .env.aws:
# ALLOW_SHORTING, SYSTEM_CORE_MAX_OPEN_TRADES, RISK_*, etc.) WITHOUT reverting to a stale
# local :latest image.
#
# WHY THIS EXISTS
#   docker-compose.yml pins the backend image via:
#       image: ${BACKEND_IMAGE:-<registry>/atp-backend:latest}
#   A plain `docker compose up -d --force-recreate backend-aws` with BACKEND_IMAGE unset
#   falls back to :latest. The host's LOCAL :latest is frequently stale (the CI deploy
#   pulls & runs the per-commit digest, it does not refresh the host's local :latest), so
#   the recreate silently REVERTS the running backend to old code — losing deployed fixes.
#   This once left production running a days-old image with critical trading fixes missing.
#
# WHAT THIS DOES
#   Resolves the image the CURRENTLY-RUNNING backend-aws container uses (the deployed code),
#   and recreates pinned to it. If it cannot resolve a real pinned digest (or only finds
#   :latest), it REFUSES to proceed rather than risk a silent revert.
#
# USAGE (run from the compose directory on the host, after editing .env.aws):
#   ./scripts/aws/safe_recreate_backend.sh
#   COMPOSE_FILE=/home/ubuntu/crypto-2.0/docker-compose.yml ./scripts/aws/safe_recreate_backend.sh

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DC=(docker compose -f "${COMPOSE_FILE}")

# 1) Image the running backend-aws container is actually using (the deployed digest).
CID="$("${DC[@]}" ps -q backend-aws 2>/dev/null || true)"
RUNNING_IMAGE=""
if [ -n "${CID}" ]; then
  RUNNING_IMAGE="$(docker inspect --format='{{.Config.Image}}' "${CID}" 2>/dev/null || true)"
fi

# 2) Fallback: BACKEND_IMAGE already pinned in .env by the deploy workflow.
if [ -z "${RUNNING_IMAGE}" ] && [ -f .env ]; then
  RUNNING_IMAGE="$(grep -E '^BACKEND_IMAGE=' .env | tail -1 | cut -d= -f2- || true)"
fi

# 3) Refuse to proceed if we cannot pin a real image (avoid the :latest revert trap).
if [ -z "${RUNNING_IMAGE}" ] || printf '%s' "${RUNNING_IMAGE}" | grep -qE ':latest$'; then
  echo "ERROR: could not resolve a pinned backend image (got '${RUNNING_IMAGE:-<empty>}')." >&2
  echo "Refusing to recreate: falling back to :latest could silently revert deployed code." >&2
  echo "Fix: pin BACKEND_IMAGE to the deployed digest, e.g." >&2
  echo "  BACKEND_IMAGE=<registry>/atp-backend:<sha> ${DC[*]} up -d --force-recreate --no-deps backend-aws backend-aws-canary" >&2
  exit 1
fi

echo "Recreating backend-aws + canary pinned to: ${RUNNING_IMAGE}"
BACKEND_IMAGE="${RUNNING_IMAGE}" "${DC[@]}" up -d --force-recreate --no-deps backend-aws backend-aws-canary
echo "Done — recreated with the pinned image (no revert). Verify: docker inspect --format '{{.Image}}' \$(${DC[*]} ps -q backend-aws)"
