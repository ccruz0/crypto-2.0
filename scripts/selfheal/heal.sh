#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"

LOCK="/var/lock/atp-selfheal.lock"
BASE="http://127.0.0.1:8002"
DEPLOY_MARKER="${ATP_DEPLOY_MARKER:-/tmp/atp-deploy-in-progress}"
DEPLOY_MARKER_TTL="${ATP_DEPLOY_MARKER_TTL_SECS:-1800}"
COOLDOWN_FILE="${ATP_SELFHEAL_COOLDOWN_FILE:-/tmp/atp-selfheal-last-action}"
COOLDOWN_SECS="${ATP_SELFHEAL_COOLDOWN_SECS:-900}"

DRY_RUN=0
ALLOW_DESTRUCTIVE=0
REASON=""

parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --dry-run)
        DRY_RUN=1
        shift
        ;;
      *)
        REASON="$1"
        shift
        ;;
    esac
  done
  if [ "${ATP_SELFHEAL_DRY_RUN:-}" = "1" ]; then
    DRY_RUN=1
  fi
  if [ "${ATP_SELFHEAL_ALLOW_DESTRUCTIVE:-}" = "1" ]; then
    ALLOW_DESTRUCTIVE=1
  fi
}

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

check_deploy_marker() {
  [ -f "$DEPLOY_MARKER" ] || return 0
  local now epoch age
  now="$(date +%s)"
  epoch="$(sed -n 's/.*epoch=\([0-9]\{1,\}\).*/\1/p' "$DEPLOY_MARKER" 2>/dev/null | head -1)"
  if [ -z "$epoch" ]; then
    epoch="$(stat -c %Y "$DEPLOY_MARKER" 2>/dev/null || echo 0)"
  fi
  age=$((now - epoch))
  if [ "$age" -lt "$DEPLOY_MARKER_TTL" ]; then
    echo "DEPLOY_IN_PROGRESS: skipping self-heal"
    exit 0
  fi
  # Stale marker: deploy process likely died without cleanup. Remove it so
  # recovery is not blocked indefinitely.
  echo "STALE_DEPLOY_MARKER: age=${age}s >= ttl=${DEPLOY_MARKER_TTL}s; removing and proceeding"
  rm -f "$DEPLOY_MARKER" 2>/dev/null || true
}

check_cooldown() {
  if [ ! -f "$COOLDOWN_FILE" ]; then
    return 0
  fi
  local last now elapsed
  last="$(cat "$COOLDOWN_FILE" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  elapsed=$((now - last))
  if [ "$elapsed" -lt "$COOLDOWN_SECS" ]; then
    echo "COOLDOWN: last recovery attempt ${elapsed}s ago (minimum ${COOLDOWN_SECS}s); skipping"
    exit 0
  fi
}

record_action() {
  date +%s >"$COOLDOWN_FILE"
}

runtime_env_status() {
  local path="$REPO_DIR/secrets/runtime.env"
  if [ ! -f "$path" ]; then
    echo "missing"
    return
  fi
  if [ -r "$path" ]; then
    echo "readable"
    return
  fi
  echo "permission_denied"
}

ensure_runtime_env_for_compose() {
  local path="$REPO_DIR/secrets/runtime.env"
  local render="$REPO_DIR/scripts/aws/render_runtime_env.sh"

  if [ -r "$path" ]; then
    return 0
  fi

  echo "secrets/runtime.env not readable by $(whoami); using render_runtime_env.sh (same path as deploy)"
  if [ ! -x "$render" ]; then
    echo "ERROR: $render not found; cannot render runtime.env for compose" >&2
    return 1
  fi
  REPO_DIR="$REPO_DIR" bash "$render" || {
    echo "ERROR: render_runtime_env.sh failed" >&2
    return 1
  }
  if [ ! -r "$path" ]; then
    echo "ERROR: secrets/runtime.env still not readable after render (expected owner $(whoami), mode 600)" >&2
    return 1
  fi
  return 0
}

collect_diagnostics() {
  local reason="${1:-}"
  echo "=== self-heal diagnostics ==="
  echo "timestamp: $(date -Is)"
  echo "reason: ${reason:-none}"
  echo "repo: $REPO_DIR"
  echo "user: $(whoami)"
  echo "runtime.env: $(runtime_env_status)"
  echo "disk:"
  df -h / 2>/dev/null || true
  if command -v docker >/dev/null 2>&1; then
    echo "containers:"
    docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || echo "  (docker ps failed)"
    echo "unhealthy:"
    docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -i unhealthy || echo "  none"
  else
    echo "containers: (docker not in PATH)"
  fi
  echo "api/health:"
  curl -sS --max-time 5 "$BASE/api/health" 2>/dev/null || echo "  unreachable"
  echo "api/health/system:"
  curl -sS --max-time 5 "$BASE/api/health/system" 2>/dev/null || echo "  unreachable"
}

log_manual_action() {
  local action="$1"
  echo "RECOMMENDED_MANUAL_ACTION: $action"
}

plan_disk_actions() {
  local d="${1:-0}"
  echo "  - truncate Docker container logs under /var/lib/docker/containers/"
  echo "  - prune Docker build cache (>24h)"
  echo "  - docker image prune (dangling and >48h unused)"
  echo "  - vacuum journal logs (3 days)"
  echo "  - clean /tmp, /var/tmp, apt cache, old app logs"
  if [ "$d" -ge 95 ]; then
    echo "  - ESCALATION: docker volume prune and docker system prune (disk >= 95%)"
  fi
}

plan_service_actions() {
  echo "  - ensure .env.aws via scripts/aws/ensure_env_aws.sh"
  echo "  - render secrets/runtime.env via scripts/aws/render_runtime_env.sh if unreadable"
  echo "  - sudo systemctl restart docker"
  echo "  - docker compose --profile aws up -d --remove-orphans"
  echo "  - docker compose --profile aws restart"
  echo "  - POST $BASE/api/health/fix"
  echo "  - sudo systemctl reload nginx (if nginx -t passes)"
}

dry_run_main() {
  echo "DRY_RUN: REPO_DIR=$REPO_DIR"
  local d
  d="$(disk_pct || echo 100)"
  d="${d//[^0-9]/}"
  [ -z "$d" ] && d=100
  echo "DRY_RUN: disk_pct=${d}%"
  echo "DRY_RUN: runtime.env=$(runtime_env_status)"

  local api_ok="unreachable"
  local health_json
  if health_json="$(curl -sS --max-time 5 "$BASE/api/health" 2>/dev/null)"; then
    api_ok="$(echo "$health_json" | jq -r '.status // "missing"' 2>/dev/null || echo "unparseable")"
  fi
  echo "DRY_RUN: api_health=${api_ok}"
  echo "DRY_RUN: verify_reason=${REASON:-none}"
  echo "DRY_RUN: allow_destructive=${ALLOW_DESTRUCTIVE}"
  echo "DRY_RUN: container_health=skipped (no docker in dry-run)"

  echo "DRY_RUN: planned_actions:"
  if [ "$d" -ge 90 ]; then
    echo "  path: disk_cleanup"
    plan_disk_actions "$d"
  else
    echo "  path: service_recovery"
    plan_service_actions
  fi
  if [ "$ALLOW_DESTRUCTIVE" != "1" ]; then
    echo "DRY_RUN: note: destructive actions gated; set ATP_SELFHEAL_ALLOW_DESTRUCTIVE=1 to enable"
  fi
}

# ---------------------------------------------------------------------------
# Disk cleanup (destructive; requires ATP_SELFHEAL_ALLOW_DESTRUCTIVE=1)
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

  after="${after//[^0-9]/}"
  if [ -n "$after" ] && [ "$after" -ge 95 ]; then
    echo "  Still critical (${after}%). Pruning unused Docker volumes..."
    docker volume prune -f 2>/dev/null || true
    docker system prune -f 2>/dev/null || true
    after="$(disk_pct || echo '?')"
    echo "  Disk after aggressive cleanup: ${after}%"
  fi
}

safe_disk_response() {
  local d="${1:-0}"
  collect_diagnostics "FAIL:DISK:${d}%"
  log_manual_action "Free disk space manually: truncate Docker logs, prune images, vacuum journal. Do not enable destructive self-heal without review."
  echo "SAFE_MODE: disk at ${d}% — diagnostics collected, no cleanup performed"
  return 2
}

# ---------------------------------------------------------------------------
# Service healing (destructive; requires ATP_SELFHEAL_ALLOW_DESTRUCTIVE=1)
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

  ensure_runtime_env_for_compose || return 1

  sudo systemctl restart docker || true
  sleep 5
  docker compose --profile aws up -d --remove-orphans
  docker compose --profile aws restart || true

  curl -sS -X POST --max-time 10 "$BASE/api/health/fix" >/dev/null 2>&1 || true

  if sudo nginx -t 2>/dev/null; then
    sudo systemctl reload nginx
  fi
}

safe_service_response() {
  local reason="${1:-}"
  collect_diagnostics "$reason"
  log_manual_action "Investigate verify failure and restart services manually if needed. Do not use destructive self-heal without ATP_SELFHEAL_ALLOW_DESTRUCTIVE=1."
  echo "SAFE_MODE: service recovery skipped (reason=${reason:-none})"
  return 2
}

main() {
  parse_args "$@"

  if [ "$DRY_RUN" = "1" ]; then
    dry_run_main
    exit 0
  fi

  check_deploy_marker
  check_cooldown
  with_lock
  record_action

  echo "Self-heal start: $(date -Is)"

  local d
  d="$(disk_pct || echo 100)"
  d="${d//[^0-9]/}"
  [ -z "$d" ] && d=100

  if [ "$d" -ge 90 ]; then
    if [ "$ALLOW_DESTRUCTIVE" = "1" ]; then
      heal_disk "$d"
      echo "Self-heal end (disk): $(date -Is)"
      exit 0
    fi
    safe_disk_response "$d"
    exit 2
  fi

  if [ "$ALLOW_DESTRUCTIVE" = "1" ]; then
    heal_services
    echo "Self-heal end (services): $(date -Is)"
    exit 0
  fi

  safe_service_response "$REASON"
  exit 2
}

main "$@"
