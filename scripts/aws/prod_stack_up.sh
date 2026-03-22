#!/usr/bin/env bash
# Run on PROD (EC2) after cd to repo root. Used by deploy_production_via_ssm.sh.
# Ensures Postgres is healthy before backend-aws (avoids compose failing on db dependency).
#
# Env: SKIP_REBUILD=0|1  NO_CACHE=0|1  (optional)

set -euo pipefail

REPO_ROOT="$(pwd)"
export COMPOSE_PROFILES=aws

_compose_ec=0
_compose_svc_out="$(docker compose --profile aws config --services 2>&1)" || _compose_ec=$?
if ! printf '%s\n' "$_compose_svc_out" | grep -q '^db$'; then
  echo "ERROR: db service not in compose aws profile (cwd=$REPO_ROOT)" >&2
  echo "docker compose --profile aws config --services (exit=${_compose_ec}):" >&2
  echo "$_compose_svc_out" >&2
  docker compose version 2>&1 || true
  exit 1
fi

echo "==> docker compose up -d db"
docker compose --profile aws up -d db

echo "==> wait for postgres_hardened healthy (max ~120s)"
_db_ok=0
# First pg_isready checks can briefly report unhealthy during init; don't bail until grace elapsed.
_DB_UNHEALTHY_GRACE_ITER="${DB_HEALTH_UNHEALTHY_GRACE_ITER:-18}"
for _i in $(seq 1 40); do
  _st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}no-health{{end}}' postgres_hardened 2>/dev/null || echo missing)"
  echo "   [${_i}] health=${_st}"
  if [[ "${_st}" == "healthy" ]]; then
    _db_ok=1
    break
  fi
  if [[ "${_st}" == "unhealthy" ]] && [[ "${_i}" -ge "${_DB_UNHEALTHY_GRACE_ITER}" ]]; then
    echo "==> postgres is unhealthy (after ${_i}*3s) — compose logs + inspect:" >&2
    docker compose --profile aws logs db --tail 120 2>&1 || true
    docker logs postgres_hardened --tail 80 2>&1 || true
    docker inspect postgres_hardened --format '{{.State.Status}} {{.State.Error}}' 2>&1 || true
    exit 1
  fi
  if [[ "${_st}" == "unhealthy" ]] && [[ "${_i}" -lt "${_DB_UNHEALTHY_GRACE_ITER}" ]]; then
    echo "   (unhealthy within grace window, waiting for recovery...)" >&2
  fi
  sleep 3
done

if [[ "${_db_ok}" != "1" ]]; then
  echo "==> timeout: postgres not healthy" >&2
  docker logs postgres_hardened --tail 100 2>&1 || true
  docker compose --profile aws ps db 2>&1 || true
  exit 1
fi

SKIP_REBUILD="${SKIP_REBUILD:-0}"
NO_CACHE="${NO_CACHE:-0}"

# Compose can reference a removed container ID ("Recreate ... No such container: <id>").
# Stop + rm the service so the next up creates a fresh container (db stays up).
_prod_reset_backend_aws() {
  echo "==> reset backend-aws container state (avoid stale recreate / missing container id)"
  docker compose --profile aws stop backend-aws 2>/dev/null || true
  docker compose --profile aws rm -f backend-aws 2>/dev/null || true
  # Name-pattern fallback if compose metadata is broken
  docker rm -f automated-trading-platform-backend-aws-1 2>/dev/null || true
}

if [[ "${SKIP_REBUILD}" == "1" ]]; then
  echo "==> SKIP_REBUILD=1: up backend-aws only"
  _prod_reset_backend_aws
  docker compose --profile aws up -d --remove-orphans backend-aws
elif [[ "${NO_CACHE}" == "1" ]]; then
  echo "==> NO_CACHE=1: build --no-cache backend-aws"
  _prod_reset_backend_aws
  docker compose --profile aws build --no-cache backend-aws 2>/dev/null || true
  docker compose --profile aws up -d --remove-orphans backend-aws
else
  echo "==> build backend-aws + up -d"
  _prod_reset_backend_aws
  docker compose --profile aws build backend-aws 2>/dev/null || true
  docker compose --profile aws up -d --remove-orphans backend-aws
fi

sleep 5
docker compose --profile aws ps backend-aws || true
curl -sS -o /dev/null -w "%{http_code}" --connect-timeout 5 http://localhost:8002/api/health || echo "000"
echo ""
