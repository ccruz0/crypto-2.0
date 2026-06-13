#!/usr/bin/env bash
# Run on PROD (EC2) from repo root **after** git is already on the desired commit.
# Resets frontend-aws container state, rebuilds, and starts frontend-aws.
#
# Git fetch/reset is done by deploy_frontend_ssm.sh (SSM) before this runs so the
# script file exists on first rollout.

set -euo pipefail

export COMPOSE_PROFILES=aws

REPO_ROOT="$(pwd)"
COMPOSE=(bash scripts/aws/prod_compose.sh)

_compose_ec=0
_compose_svc_out="$("${COMPOSE[@]}" config --services 2>&1)" || _compose_ec=$?
if [[ ! -f docker-compose.yml ]] || ! printf '%s\n' "$_compose_svc_out" | grep -q '^frontend-aws$'; then
  echo "ERROR: run from repo root with frontend-aws in aws profile (cwd=$REPO_ROOT)" >&2
  echo "docker compose --profile aws config --services (exit=${_compose_ec}):" >&2
  echo "$_compose_svc_out" >&2
  exit 1
fi

echo "==> verify clean frontend working tree (block dirty Docker build context)"
bash scripts/verify_clean_worktree.sh --frontend-only

echo "==> reset frontend-aws container (stale recreate / missing id)"
"${COMPOSE[@]}" stop frontend-aws 2>/dev/null || true
"${COMPOSE[@]}" rm -f frontend-aws 2>/dev/null || true
docker rm -f automated-trading-platform-frontend-aws-1 2>/dev/null || true

echo "==> docker compose build + up frontend-aws"
"${COMPOSE[@]}" build frontend-aws
"${COMPOSE[@]}" up -d --remove-orphans frontend-aws

sleep 5
"${COMPOSE[@]}" ps frontend-aws || true
echo "==> done"
