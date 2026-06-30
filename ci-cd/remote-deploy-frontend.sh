#!/usr/bin/env bash
# Runs ON the EC2 host (via SSM) to deploy ONLY the frontend-aws service from an
# ECR image. Never touches the trading backend or other containers.
#
# Required env (passed by deploy-frontend.yml):
#   IMAGE_NEW   full ECR image URI to deploy (e.g. <reg>/atp-frontend:sha-abc123)
#   SERVICE     compose service name (frontend-aws)
#   REGION      AWS region
#   REGISTRY    ECR registry host (<acct>.dkr.ecr.<region>.amazonaws.com)
#   COMPOSE_DIR repo dir on host (e.g. /home/ubuntu/crypto-2.0)
set -uo pipefail

: "${IMAGE_NEW:?IMAGE_NEW is required}"
: "${SERVICE:?SERVICE is required}"
: "${REGION:?REGION is required}"
: "${REGISTRY:?REGISTRY is required}"
: "${COMPOSE_DIR:?COMPOSE_DIR is required}"

cd "$COMPOSE_DIR" || { echo "COMPOSE_DIR not found: $COMPOSE_DIR"; exit 1; }

# Capture the image of the currently running container for rollback.
CID="$(docker ps -q -f "name=^/${SERVICE}$" | head -1)"
PREV_IMG=""
if [ -n "$CID" ]; then
  PREV_IMG="$(docker inspect --format '{{.Config.Image}}' "$CID" 2>/dev/null || true)"
fi
echo "Current ${SERVICE} image: ${PREV_IMG:-<none>}"

echo "ECR login..."
aws ecr get-login-password --region "$REGION" \
  | docker login --username AWS --password-stdin "$REGISTRY" \
  || { echo "ECR login failed"; exit 1; }

echo "Pulling ${IMAGE_NEW}"
docker pull "$IMAGE_NEW" || { echo "docker pull failed"; exit 1; }

deploy() { IMAGE="$1" docker compose --profile aws up -d --no-deps "$SERVICE"; }

health() {
  local ok=1 path code
  for path in / /peluqueria; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "http://localhost:3000${path}" || echo 000)"
    echo "  health ${path} -> ${code}"
    case "$code" in 2*|3*) ;; *) ok=0 ;; esac
  done
  [ "$ok" = "1" ]
}

echo "Deploying ${IMAGE_NEW} to ${SERVICE} (no-deps; backend untouched)"
deploy "$IMAGE_NEW" || { echo "compose up failed"; exit 1; }

RC=1
for i in $(seq 1 12); do
  sleep 5
  if health; then RC=0; break; fi
  echo "  not healthy yet ($i/12)"
done

if [ "$RC" -ne 0 ]; then
  echo "Health check failed - rolling back"
  if [ -n "$PREV_IMG" ]; then
    deploy "$PREV_IMG" && echo "rolled back to ${PREV_IMG}" || echo "rollback failed"
  else
    echo "no previous image captured; cannot auto-roll back"
  fi
  exit 1
fi

echo "${SERVICE} healthy on ${IMAGE_NEW}"
