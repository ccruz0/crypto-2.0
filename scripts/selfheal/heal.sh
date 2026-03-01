#!/usr/bin/env bash
set -euo pipefail

LOCK="/var/lock/atp-selfheal.lock"
BASE="http://127.0.0.1:8002"

with_lock() {
  exec 9>"$LOCK"
  if ! flock -n 9; then
    echo "Another self-heal is running. Exiting."
    exit 0
  fi
}

disk_pct() {
  df -P / | awk 'NR==2 {gsub("%","",$5); print $5}'
}

truncate_docker_logs() {
  sudo find /var/lib/docker/containers/ -name "*-json.log" -type f -exec truncate -s 0 {} \; || true
}

docker_prune() {
  docker system prune -af || true
  docker builder prune -af || true
}

restart_stack() {
  local repo_dir="${1:-$HOME/automated-trading-platform}"
  local env_file="$repo_dir/.env"
  if [ ! -f "$env_file" ]; then
    echo ".env missing at $env_file. Copy .env.example to .env and set DATABASE_URL/POSTGRES_PASSWORD. Skipping compose."
    return 0
  fi
  cd "$repo_dir"
  if [ -x scripts/aws/ensure_env_aws.sh ]; then
    REPO_DIR="$repo_dir" ./scripts/aws/ensure_env_aws.sh || true
  fi
  if [ ! -f .env.aws ]; then
    echo ".env.aws still missing after ensure_env_aws; skipping compose restart."
    return 0
  fi
  docker compose --profile aws up -d --remove-orphans
  docker compose --profile aws restart || true
}

nginx_safe_reload() {
  if sudo nginx -t; then
    sudo systemctl reload nginx
  fi
}

call_unprotected_health_fix() {
  # POST only. Ignore 404/405/timeouts.
  curl -sS -X POST --max-time 10 "$BASE/api/health/fix" >/dev/null 2>&1 || true
}

main() {
  with_lock
  echo "Self-heal start: $(date -Is)"

  local d
  d="$(disk_pct || echo 100)"
  d="${d//[^0-9]/}"
  [[ -z "$d" ]] && d=100
  if [ "$d" -ge 90 ]; then
    echo "Disk high (${d}%). Truncating docker logs + pruning."
    truncate_docker_logs
    docker_prune
  fi

  echo "Restarting docker"
  sudo systemctl restart docker || true

  echo "Restarting stack"
  restart_stack "$HOME/automated-trading-platform"

  echo "Calling unprotected /api/health/fix"
  call_unprotected_health_fix

  echo "Nginx safe reload"
  nginx_safe_reload

  echo "Self-heal end: $(date -Is)"
}

main "$@"
