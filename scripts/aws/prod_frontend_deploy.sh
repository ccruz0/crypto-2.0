#!/usr/bin/env bash
# Run on PROD (EC2) from repo root after `cd` to automated-trading-platform (or crypto-2.0).
# Pulls latest main, updates frontend submodule if present, rebuilds and restarts frontend-aws.
#
# Used by deploy_frontend_ssm.sh (SSM).

set -euo pipefail

export HOME="${HOME:-/home/ubuntu}"
export COMPOSE_PROFILES=aws

for _d in /home/ubuntu/automated-trading-platform /home/ubuntu/crypto-2.0; do
  git config --global --add safe.directory "$_d" 2>/dev/null || true
done

REPO_ROOT="$(pwd)"
_compose_ec=0
_compose_svc_out="$(docker compose --profile aws config --services 2>&1)" || _compose_ec=$?
if [[ ! -f docker-compose.yml ]] || ! printf '%s\n' "$_compose_svc_out" | grep -q '^frontend-aws$'; then
  echo "ERROR: run from repo root with frontend-aws in aws profile (cwd=$REPO_ROOT)" >&2
  echo "docker compose --profile aws config --services (exit=${_compose_ec}):" >&2
  echo "$_compose_svc_out" >&2
  exit 1
fi

echo "==> git: fetch main + reset to FETCH_HEAD"
rm -f .git/refs/remotes/origin/main 2>/dev/null || true
git fetch origin main
git reset --hard FETCH_HEAD 2>/dev/null || git reset --hard origin/main

echo "==> git submodule update (if .gitmodules present)"
git submodule update --init --recursive 2>/dev/null || true

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
