#!/usr/bin/env bash
set -euo pipefail

LOCK="/var/lock/atp-selfheal.lock"
BASE="http://127.0.0.1:8002"
REPO_DIR="${REPO_DIR:-$HOME/automated-trading-platform}"

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

# ---------------------------------------------------------------------------
# Disk cleanup: free space WITHOUT removing images used by running containers
# and WITHOUT restarting the stack (which would trigger expensive rebuilds).
# ---------------------------------------------------------------------------
heal_disk() {
  local d="${1:-0}"
  echo "Disk at ${d}% — running targeted cleanup (no restart)."

  echo "  Truncating Docker container logs..."
  sudo find /var/lib/docker/containers/ -name "*-json.log" -type f \
    -exec truncate -s 0 {} \; 2>/dev/null || true

  echo "  Pruning Docker build cache (>24h)..."
  docker builder prune -af --filter "until=24h" 2>/dev/null || true

  echo "  Removing dangling images..."
  docker image prune -f 2>/dev/null || true

  echo "  Removing unused images older than 48h (keeps current stack)..."
  docker image prune -af --filter "until=48h" 2>/dev/null || true

  echo "  Vacuuming journal logs (keep 3 days)..."
  sudo journalctl --vacuum-time=3d 2>/dev/null || true

  echo "  Cleaning /tmp and /var/tmp (>3 days)..."
  sudo find /tmp -type f -atime +3 -delete 2>/dev/null || true
  sudo find /var/tmp -type f -atime +3 -delete 2>/dev/null || true

  echo "  Cleaning apt cache..."
  sudo apt-get clean 2>/dev/null || true

  echo "  Removing old app log files (>5MB or >3 days)..."
  find "$REPO_DIR" -maxdepth 3 -type f -name "*.log" -size +5M -delete 2>/dev/null || true
  find "$REPO_DIR" -maxdepth 3 -type f -name "*.log" -mtime +3 -delete 2>/dev/null || true

  local after
  after="$(disk_pct || echo '?')"
  echo "  Disk after cleanup: ${after}%"

  # If still critically high (>=95%), escalate to full prune of unused volumes
  after="${after//[^0-9]/}"
  if [[ -n "$after" ]] && [ "$after" -ge 95 ]; then
    echo "  Still critical (${after}%). Pruning unused Docker volumes..."
    docker volume prune -f 2>/dev/null || true
    docker system prune -f 2>/dev/null || true
    after="$(disk_pct || echo '?')"
    echo "  Disk after aggressive cleanup: ${after}%"
  fi
}

# ---------------------------------------------------------------------------
# Service healing: restart unhealthy containers / the full stack.
# ---------------------------------------------------------------------------
heal_services() {
  echo "Service issue detected — restarting stack."

  local env_file="$REPO_DIR/.env"
  if [ ! -f "$env_file" ]; then
    echo ".env missing at $env_file. Skipping compose restart."
    return 0
  fi

  cd "$REPO_DIR"
  if [ -x scripts/aws/ensure_env_aws.sh ]; then
    REPO_DIR="$REPO_DIR" ./scripts/aws/ensure_env_aws.sh || true
  fi
  if [ ! -f .env.aws ]; then
    echo ".env.aws still missing after ensure_env_aws; skipping compose restart."
    return 0
  fi

  sudo systemctl restart docker || true
  sleep 5
  docker compose --profile aws up -d --remove-orphans
  docker compose --profile aws restart || true

  curl -sS -X POST --max-time 10 "$BASE/api/health/fix" >/dev/null 2>&1 || true

  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx
  fi
}

main() {
  with_lock
  echo "Self-heal start: $(date -Is)"

  local d
  d="$(disk_pct || echo 100)"
  d="${d//[^0-9]/}"
  [[ -z "$d" ]] && d=100

  local reason="${1:-}"

  if [ "$d" -ge 90 ]; then
    heal_disk "$d"
    # Disk-only issue: don't restart the stack (avoids rebuild cycle).
    # If other services are also broken, the next 2-minute tick will
    # detect them and run heal_services.
    echo "Self-heal end (disk): $(date -Is)"
    exit 0
  fi

  heal_services

  echo "Self-heal end (services): $(date -Is)"
}

main "$@"
