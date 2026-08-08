#!/usr/bin/env bash
# Safely recreate frontend-aws after an env-var / compose change WITHOUT reverting
# to a stale local :latest image.
#
# WHY THIS EXISTS
#   docker-compose.yml pins the frontend image via:
#       image: ${FRONTEND_IMAGE:-${IMAGE:-<registry>/atp-frontend:latest}}
#   A plain `docker compose up -d --force-recreate frontend-aws` with those unset
#   falls back to :latest. The host's LOCAL :latest is frequently stale (the CI
#   deploy pulls & runs the per-commit tag; before the pin/retag fix it did not
#   refresh host :latest), so the recreate silently REVERTS the running frontend.
#   Seen in prod after #409: FE sha healthy, then recreate onto stale :latest
#   during a parallel backend deploy.
#
# WHAT THIS DOES
#   Resolves the image the CURRENTLY-RUNNING frontend-aws container uses (the
#   deployed digest), and recreates pinned to it. If it cannot resolve a real
#   pinned digest (or only finds :latest), it REFUSES to proceed.
#
# USAGE (run from the compose directory on the host):
#   ./scripts/aws/safe_recreate_frontend.sh
#   COMPOSE_FILE=/home/ubuntu/crypto-2.0/docker-compose.yml ./scripts/aws/safe_recreate_frontend.sh

set -euo pipefail

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DC=(docker compose -f "${COMPOSE_FILE}")

# 1) Image the running frontend-aws container is actually using.
CID="$("${DC[@]}" ps -q frontend-aws 2>/dev/null || true)"
RUNNING_IMAGE=""
if [ -n "${CID}" ]; then
  RUNNING_IMAGE="$(docker inspect --format='{{.Config.Image}}' "${CID}" 2>/dev/null || true)"
fi

# 2) Fallback: FRONTEND_IMAGE (or legacy IMAGE) already pinned in .env by deploy.
if [ -z "${RUNNING_IMAGE}" ] && [ -f .env ]; then
  RUNNING_IMAGE="$(grep -E '^FRONTEND_IMAGE=' .env | tail -1 | cut -d= -f2- || true)"
fi
if [ -z "${RUNNING_IMAGE}" ] && [ -f .env ]; then
  RUNNING_IMAGE="$(grep -E '^IMAGE=' .env | tail -1 | cut -d= -f2- || true)"
fi

# 3) Refuse to proceed if we cannot pin a real image (avoid the :latest revert trap).
if [ -z "${RUNNING_IMAGE}" ] || printf '%s' "${RUNNING_IMAGE}" | grep -qE ':latest$'; then
  echo "ERROR: could not resolve a pinned frontend image (got '${RUNNING_IMAGE:-<empty>}')." >&2
  echo "Refusing to recreate: falling back to :latest could silently revert deployed UI." >&2
  echo "Fix: pin FRONTEND_IMAGE to the deployed digest, e.g." >&2
  echo "  FRONTEND_IMAGE=<registry>/atp-frontend:sha-<commit> ${DC[*]} up -d --force-recreate --no-deps frontend-aws" >&2
  exit 1
fi

echo "Recreating frontend-aws pinned to: ${RUNNING_IMAGE}"
FRONTEND_IMAGE="${RUNNING_IMAGE}" IMAGE="${RUNNING_IMAGE}" \
  "${DC[@]}" --profile aws up -d --force-recreate --no-deps frontend-aws
echo "Done — recreated with the pinned image (no revert). Verify: docker inspect --format '{{.Config.Image}}' \$(${DC[*]} ps -q frontend-aws)"
