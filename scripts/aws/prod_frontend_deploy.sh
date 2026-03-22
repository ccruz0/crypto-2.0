#!/usr/bin/env bash
# Run on PROD (EC2) from repo root **after** git is already on the desired commit.
# Resets frontend-aws container state, rebuilds, and starts frontend-aws.
#
# Git fetch/reset is done by deploy_frontend_ssm.sh (SSM) before this runs so the
# script file exists on first rollout.

set -euo pipefail

export COMPOSE_PROFILES=aws

REPO_ROOT="$(pwd)"
_compose_ec=0
_compose_svc_out="$(docker compose --profile aws config --services 2>&1)" || _compose_ec=$?
if [[ ! -f docker-compose.yml ]] || ! printf '%s\n' "$_compose_svc_out" | grep -q '^frontend-aws$'; then
  echo "ERROR: run from repo root with frontend-aws in aws profile (cwd=$REPO_ROOT)" >&2
  echo "docker compose --profile aws config --services (exit=${_compose_ec}):" >&2
  echo "$_compose_svc_out" >&2
  exit 1
fi

echo "==> reset frontend-aws container (stale recreate / missing id)"
docker compose --profile aws stop frontend-aws 2>/dev/null || true
docker compose --profile aws rm -f frontend-aws 2>/dev/null || true
docker rm -f automated-trading-platform-frontend-aws-1 2>/dev/null || true

echo "==> docker compose build + up frontend-aws"
docker compose --profile aws build frontend-aws
docker compose --profile aws up -d --remove-orphans frontend-aws

sleep 5
docker compose --profile aws ps frontend-aws || true
echo "==> done"
