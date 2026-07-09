#!/usr/bin/env bash
# Targeted remediation for FAIL:SIGNAL_MONITOR from verify.sh / health-alert.
# Order: POST /api/health/fix (in-process) → verify → docker restart backend-aws if still FAIL.
#
# Env:
#   REPO_DIR                         repo root (default: derived from script location)
#   ATP_HEALTH_BASE                  backend base URL (default: http://127.0.0.1:8002)
#   ATP_REMEDIATE_DRY_RUN=1            log only
#   ATP_REMEDIATE_SIGNAL_MONITOR_GRACE_SEC  wait after health/fix (default: 45)
#   ATP_REMEDIATE_BACKEND_RESTART_GRACE_SEC wait after container restart (default: 60)
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="${REPO_DIR:-$(cd "$SCRIPT_DIR/../.." && pwd)}"
BASE="${ATP_HEALTH_BASE:-http://127.0.0.1:8002}"
DRY_RUN="${ATP_REMEDIATE_DRY_RUN:-0}"
HEALTH_FIX_GRACE="${ATP_REMEDIATE_SIGNAL_MONITOR_GRACE_SEC:-45}"
RESTART_GRACE="${ATP_REMEDIATE_BACKEND_RESTART_GRACE_SEC:-60}"

log() {
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] remediate_signal_monitor $*"
}

signal_monitor_status() {
  curl -sS --max-time 10 "$BASE/api/health/system" 2>/dev/null \
    | jq -r '.signal_monitor.status // "unknown"' 2>/dev/null || echo "unknown"
}

post_health_fix() {
  log "event=remediation_step action=curl_post_health_fix"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "event=remediation_step result=skipped dry_run=1 step=health_fix"
    return 0
  fi
  local code
  code="$(curl -sS -o /tmp/atp-health-fix.body -w "%{http_code}" --max-time 30 -X POST "$BASE/api/health/fix" 2>/tmp/atp-remediate-sm.curl.err)" || true
  if [[ "$code" =~ ^2[0-9][0-9]$ ]]; then
    log "event=remediation_step result=ok step=health_fix http_code=$code"
    return 0
  fi
  log "event=remediation_step result=warn step=health_fix http_code=${code:-000}"
  return 1
}

restart_backend_aws() {
  log "event=remediation_step action=docker_compose_restart_backend_aws"
  if [[ "$DRY_RUN" == "1" ]]; then
    log "event=remediation_step result=skipped dry_run=1 step=restart_backend_aws"
    return 0
  fi
  cd "$REPO_DIR" 2>/dev/null || {
    log "event=remediation_failed repo_dir_missing path=$REPO_DIR"
    return 1
  }
  set +e
  if docker compose --profile aws restart backend-aws >>/tmp/atp-remediate-sm.log 2>&1; then
    log "event=remediation_step result=ok step=restart_backend_aws"
    set -e
    return 0
  fi
  local cnt
  cnt="$(docker ps -aq --filter name=automated-trading-platform-backend-aws 2>/dev/null | head -1)"
  if [[ -n "$cnt" ]]; then
    if docker restart "$cnt" >>/tmp/atp-remediate-sm.log 2>&1; then
      log "event=remediation_step result=ok step=docker_restart_container id=$cnt"
      set -e
      return 0
    fi
  fi
  set -e
  log "event=remediation_step result=fail step=restart_backend_aws"
  return 1
}

main() {
  log "event=remediation_started dry_run=$DRY_RUN reason=${1:-FAIL:SIGNAL_MONITOR}"

  post_health_fix || true

  if [[ "$DRY_RUN" != "1" ]] && [[ "$HEALTH_FIX_GRACE" -gt 0 ]] 2>/dev/null; then
    sleep "$HEALTH_FIX_GRACE"
  fi

  local sm_status
  sm_status="$(signal_monitor_status)"
  log "event=post_health_fix_check signal_monitor_status=$sm_status"
  if [[ "$sm_status" == "PASS" ]]; then
    log "event=remediation_finished result=pass_after_health_fix"
    exit 0
  fi

  restart_backend_aws || true

  if [[ "$DRY_RUN" != "1" ]] && [[ "$RESTART_GRACE" -gt 0 ]] 2>/dev/null; then
    sleep "$RESTART_GRACE"
  fi

  sm_status="$(signal_monitor_status)"
  log "event=post_restart_check signal_monitor_status=$sm_status"
  if [[ "$sm_status" == "PASS" ]]; then
    log "event=remediation_finished result=pass_after_backend_restart"
    exit 0
  fi

  log "event=remediation_finished result=still_fail signal_monitor_status=$sm_status"
  exit 1
}

main "$@"
