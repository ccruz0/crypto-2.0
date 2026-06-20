#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Pre-build disk-capacity guard for the ATP deploy.
#
# PROBLEM THIS SOLVES
#   Production deploys build a fresh image set with `docker compose build`
#   while the previous stack keeps running (deploy resiliency / "Outcome B").
#   The new layers plus the retained old images can exceed the free space on
#   the small (~29 GB) root volume, so the build dies with
#   "no space left on device" and the new image is never produced.
#
#   The daily cleanup cron (infra/cleanup_disk.sh, 02:00) and the post-`up`
#   prune both run at the WRONG moment — never right before the build. This
#   script closes that gap: it reclaims space *immediately before* the build,
#   idempotently and production-safely.
#
# SAFETY GUARANTEES
#   * NEVER removes named volumes — no `docker volume prune`, no `-v`,
#     no `docker system prune --volumes`. Postgres / Prometheus / Grafana
#     data is untouched.
#   * NEVER removes images in use by a running OR stopped container. Docker
#     protects those; the live stack the deploy is keeping up is safe.
#   * NEVER runs `docker compose down` and never restarts containers.
#   * Best-effort: every reclaim step is guarded; a failing step never aborts
#     the deploy. Exits non-zero only when DISK_GUARD_STRICT=1 and space is
#     still below the floor after all safe reclamation.
#
# RECLAMATION TIERS (safe first, escalate only if still tight)
#   Tier 1 (always): dangling images, build cache >24h, stopped containers,
#                    unused networks, container json logs, journal, apt cache.
#   Tier 2 (only if free < MIN_FREE_GB): all unused images + full build cache.
#
# USAGE
#   bash scripts/aws/predeploy_disk_guard.sh
#   MIN_FREE_GB=8 bash scripts/aws/predeploy_disk_guard.sh
#   DISK_GUARD_STRICT=1 bash scripts/aws/predeploy_disk_guard.sh   # fail deploy if still short
# ---------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# --- configuration (all overridable via env) -------------------------------
TARGET_MOUNT="${DISK_GUARD_MOUNT:-/}"
MIN_FREE_GB="${MIN_FREE_GB:-6}"          # space we want free before building all services
STRICT="${DISK_GUARD_STRICT:-0}"         # 1 => exit 1 if still below floor after reclaim
DRY_RUN="${DISK_GUARD_DRY_RUN:-0}"       # 1 => report + decide tiers but run no destructive command
LOG_FILE="${DISK_GUARD_LOG:-/tmp/atp-predeploy-disk.log}"
# node_exporter textfile collector dir (metrics only written if it exists)
METRICS_DIR="${DISK_GUARD_METRICS_DIR:-/var/lib/node_exporter/textfile_collector}"

# Pick a writable log file. A prior run (e.g. as root) may have created the
# default path owned by another user; fall back so logging never errors.
if ! ( : >> "$LOG_FILE" ) 2>/dev/null; then
  LOG_FILE="$(mktemp /tmp/atp-predeploy-disk.XXXXXX.log 2>/dev/null || echo /dev/null)"
fi

log() { echo "[predeploy_disk_guard] $*" | tee -a "$LOG_FILE" 2>/dev/null || echo "[predeploy_disk_guard] $*"; }

# Run a destructive reclaim command, unless DRY_RUN=1 (then just log it).
run() {
  if [ "$DRY_RUN" = "1" ]; then
    log "DRY_RUN skip: $*"
    return 0
  fi
  "$@"
}

free_kb()  { df -Pk "$TARGET_MOUNT" 2>/dev/null | awk 'NR==2 {print $4}'; }
used_pct() { df -P "$TARGET_MOUNT" 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}'; }
free_gb()  { awk "BEGIN { printf \"%.2f\", $(free_kb) / 1024 / 1024 }"; }

report_usage() {
  log "--- df -h $TARGET_MOUNT ---"
  df -h "$TARGET_MOUNT" 2>/dev/null | tee -a "$LOG_FILE" 2>/dev/null || df -h "$TARGET_MOUNT"
  log "--- docker system df ---"
  docker system df 2>/dev/null | tee -a "$LOG_FILE" 2>/dev/null || docker system df 2>/dev/null || true
}

# Tier 1: the safe daily-cleanup logic (no volumes, no running-stack images).
tier1_safe_reclaim() {
  log "Tier 1: safe reclaim (dangling images, build cache >24h, stopped containers, networks, logs)"
  if [ -x "$ROOT_DIR/infra/cleanup_disk.sh" ]; then
    # cleanup_disk.sh is the audited, volume-safe daily cleanup. Reuse it so
    # there is a single source of truth for "what is safe to delete".
    run bash "$ROOT_DIR/infra/cleanup_disk.sh" 2>&1 | sed 's/^/[cleanup_disk] /' | tee -a "$LOG_FILE" 2>/dev/null || true
  else
    log "WARN: infra/cleanup_disk.sh not found — running inline safe prune"
    run docker image prune -f 2>/dev/null || true
    run docker image prune -af --filter "until=48h" 2>/dev/null || true
    run docker builder prune -af --filter "until=24h" 2>/dev/null || true
    run docker container prune -f 2>/dev/null || true
    run docker network prune -f 2>/dev/null || true
    run sudo find /var/lib/docker/containers/ -name "*-json.log" -type f -exec truncate -s 0 {} \; 2>/dev/null || true
    run sudo journalctl --vacuum-time=5d 2>/dev/null || true
    run sudo apt-get clean 2>/dev/null || true
  fi
  # Fully purge build cache. The deploy builds with --no-cache, so cached layers
  # are never reused; keeping them only wastes space. This also reclaims cache
  # leaked by a previous interrupted/failed build (which cleanup_disk.sh's
  # "until=24h" filter misses on the same day).
  log "Tier 1: purging ALL build cache (docker builder prune -af)"
  run docker builder prune -af 2>/dev/null || true
}

# Tier 2: remove ALL images not referenced by any container + full build cache.
# Still 100% volume-safe and running-stack-safe (Docker refuses to delete an
# image backing a live container).
tier2_aggressive_reclaim() {
  log "Tier 2: free=$(free_gb)GB < MIN_FREE_GB=${MIN_FREE_GB}GB — pruning ALL unused images + build cache"
  run docker builder prune -af 2>/dev/null || true
  run docker image prune -af 2>/dev/null || true
}

write_metrics() {
  # Best-effort node_exporter textfile metric. No-op if collector dir absent.
  [ -d "$METRICS_DIR" ] || return 0
  local verdict_num="$1" free_after pct_after tmp
  free_after="$(free_gb)"; pct_after="$(used_pct)"
  tmp="$(mktemp "${METRICS_DIR}/atp_predeploy_disk.prom.XXXXXX" 2>/dev/null)" || return 0
  {
    echo "# HELP atp_predeploy_disk_free_gb Free space on deploy volume after pre-build disk guard."
    echo "# TYPE atp_predeploy_disk_free_gb gauge"
    echo "atp_predeploy_disk_free_gb ${free_after}"
    echo "# HELP atp_predeploy_disk_used_percent Used percent on deploy volume after pre-build disk guard."
    echo "# TYPE atp_predeploy_disk_used_percent gauge"
    echo "atp_predeploy_disk_used_percent ${pct_after}"
    echo "# HELP atp_predeploy_disk_guard_ok 1 if free space met MIN_FREE_GB floor, else 0."
    echo "# TYPE atp_predeploy_disk_guard_ok gauge"
    echo "atp_predeploy_disk_guard_ok ${verdict_num}"
    echo "# HELP atp_predeploy_disk_guard_run_timestamp_seconds Unix time of last guard run."
    echo "# TYPE atp_predeploy_disk_guard_run_timestamp_seconds gauge"
    echo "atp_predeploy_disk_guard_run_timestamp_seconds $(date +%s)"
  } > "$tmp" 2>/dev/null && mv -f "$tmp" "${METRICS_DIR}/atp_predeploy_disk.prom" 2>/dev/null || rm -f "$tmp" 2>/dev/null || true
}

main() {
  : > "$LOG_FILE" 2>/dev/null || true
  log "start $(date -Is) mount=$TARGET_MOUNT MIN_FREE_GB=$MIN_FREE_GB strict=$STRICT"

  local before_gb before_pct after_gb after_pct reclaimed verdict_num
  before_gb="$(free_gb)"; before_pct="$(used_pct)"
  log "BEFORE: free=${before_gb}GB used=${before_pct}%"
  report_usage

  tier1_safe_reclaim

  # Escalate only if still below the floor.
  if awk "BEGIN { exit !($(free_gb) < $MIN_FREE_GB) }"; then
    tier2_aggressive_reclaim
  else
    log "Tier 1 sufficient: free=$(free_gb)GB >= MIN_FREE_GB=${MIN_FREE_GB}GB (skipping Tier 2)"
  fi

  after_gb="$(free_gb)"; after_pct="$(used_pct)"
  reclaimed="$(awk "BEGIN { printf \"%.2f\", $after_gb - $before_gb }")"
  log "AFTER:  free=${after_gb}GB used=${after_pct}% (reclaimed ${reclaimed}GB)"
  report_usage

  if awk "BEGIN { exit !($after_gb >= $MIN_FREE_GB) }"; then
    verdict_num=1
    log "RESULT: PASS — free=${after_gb}GB >= floor=${MIN_FREE_GB}GB. Build should have room."
  else
    verdict_num=0
    log "RESULT: INSUFFICIENT — free=${after_gb}GB < floor=${MIN_FREE_GB}GB after all SAFE reclamation."
    log "        Remaining usage is named volumes / running-stack images / OS — NOT safe to auto-delete."
    log "        Action: grow the EBS root volume (see docs) — do not manually delete volumes."
  fi

  write_metrics "$verdict_num"

  if [ "$verdict_num" -eq 0 ] && [ "$STRICT" = "1" ]; then
    log "STRICT mode: exiting 1 so the deploy aborts before a doomed build (previous stack keeps serving)."
    exit 1
  fi
  exit 0
}

main "$@"
