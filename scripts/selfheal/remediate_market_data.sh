#!/usr/bin/env bash
# Targeted remediation for MARKET_DATA / market_updater FAIL from verify.sh.
# Order: restart market-updater first → update-cache (long timeout + retry) → optional health/fix last.
# health/fix restarts in-process backend services and can cause empty reply / interrupt update-cache;
# default is skip health/fix for this script; set ATP_REMEDIATE_RUN_HEALTH_FIX=1 to run it after cache.
# Env:
#   REPO_DIR        repo root (default: ~/automated-trading-platform)
#   ATP_HEALTH_BASE backend base URL (default: http://127.0.0.1:8002)
#   ATP_REMEDIATE_DRY_RUN=1           log only
#   ATP_REMEDIATE_SKIP_HEALTH_FIX=1   default 1 — do not POST /api/health/fix before update-cache
#   ATP_REMEDIATE_RUN_HEALTH_FIX=1    if set, POST /api/health/fix after update-cache (optional)
#   ATP_REMEDIATE_UPDATE_CACHE_TIMEOUT_SEC  default 300 (first updater cycle can be slow)
#   ATP_REMEDIATE_UPDATE_CACHE_RETRIES      default 1 (one retry after sleep if empty reply / fail)
set -uo pipefail

REPO_DIR="${REPO_DIR:-${HOME}/automated-trading-platform}"
BASE="${ATP_HEALTH_BASE:-http://127.0.0.1:8002}"
DRY_RUN="${ATP_REMEDIATE_DRY_RUN:-0}"
SKIP_HEALTH_FIX="${ATP_REMEDIATE_SKIP_HEALTH_FIX:-1}"
RUN_HEALTH_FIX_AFTER="${ATP_REMEDIATE_RUN_HEALTH_FIX:-0}"
UPDATE_CACHE_TIMEOUT="${ATP_REMEDIATE_UPDATE_CACHE_TIMEOUT_SEC:-300}"
UPDATE_CACHE_RETRIES="${ATP_REMEDIATE_UPDATE_CACHE_RETRIES:-1}"

log() {
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] remediate_market_data $*"
}

cd "$REPO_DIR" 2>/dev/null || {
  log "event=remediation_failed repo_dir_missing path=$REPO_DIR"
  exit 1
}

if [[ "$DRY_RUN" == "1" ]]; then
  log "event=remediation_started dry_run=1 action=docker_compose_restart_market_updater_aws"
  log "event=remediation_started dry_run=1 action=curl_post_market_update_cache timeout=${UPDATE_CACHE_TIMEOUT}s retries=${UPDATE_CACHE_RETRIES}"
  log "event=remediation_started dry_run=1 action=curl_post_health_fix_after_cache optional run_health_fix_after=$RUN_HEALTH_FIX_AFTER"
  log "event=remediation_finished dry_run=1 result=skipped"
  exit 0
fi

log "event=remediation_started dry_run=0 action=docker_compose_restart_market_updater_aws"
set +e
if docker compose --profile aws restart market-updater-aws >>/tmp/atp-remediate.log 2>&1; then
  log "event=remediation_step result=ok step=restart_market_updater_aws"
else
  CNT="$(docker ps -aq --filter name=market-updater-aws | head -1)"
  if [[ -n "$CNT" ]]; then
    docker restart "$CNT" >>/tmp/atp-remediate.log 2>&1 && log "event=remediation_step result=ok step=docker_restart_container id=$CNT" || log "event=remediation_step result=fail step=docker_restart_container"
  else
    log "event=remediation_step result=fail step=restart_market_updater_aws no_container"
  fi
fi

# Let updater process start before hitting backend
sleep 10

# update-cache first (fills DB); avoid health/fix before this — it restarts backend and can empty-reply curl
do_update_cache() {
  local attempt="$1"
  log "event=remediation_started dry_run=0 action=curl_post_market_update_cache attempt=$attempt timeout=${UPDATE_CACHE_TIMEOUT}s"
  # -w to detect empty reply (http_code 000) without -f so we can retry
  code="$(curl -sS -o /tmp/atp-update-cache.body -w "%{http_code}" --max-time "$UPDATE_CACHE_TIMEOUT" -X POST "$BASE/api/market/update-cache" 2>/tmp/atp-remediate.curl.err)"
  curl_exit=$?
  if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
    log "event=remediation_step result=ok step=update_cache http_code=$code attempt=$attempt"
    return 0
  fi
  # curl 52 = empty reply from server
  if [[ "$curl_exit" -ne 0 ]] || [[ "$code" == "000" ]] || [[ -z "$code" ]]; then
    log "event=remediation_step result=warn step=update_cache curl_exit=$curl_exit http_code=${code:-000} attempt=$attempt"
    return 1
  fi
  log "event=remediation_step result=warn step=update_cache http_code=$code attempt=$attempt"
  return 1
}

if ! do_update_cache 1; then
  if [[ "${UPDATE_CACHE_RETRIES:-0}" -ge 1 ]]; then
    log "event=remediation_retry sleep=30s before_update_cache_retry"
    sleep 30
    do_update_cache 2 || true
  fi
else
  :
fi

# Optional: health/fix after cache so backend services recycled without killing update-cache mid-flight
if [[ "$RUN_HEALTH_FIX_AFTER" == "1" ]]; then
  sleep 5
  log "event=remediation_started dry_run=0 action=curl_post_health_fix_after_cache"
  if curl -sS -X POST --max-time 30 "$BASE/api/health/fix" >>/tmp/atp-remediate.log 2>&1; then
    log "event=remediation_step result=ok step=health_fix_after_cache"
  else
    log "event=remediation_step result=fail step=health_fix_after_cache"
  fi
fi

log "event=remediation_finished dry_run=0 result=done"
