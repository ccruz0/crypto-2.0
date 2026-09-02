#!/usr/bin/env bash
# Synthetic probe of primary /api/health with auto-restart of primary backend only.
# Mirrors prod hotfix on i-087953603011543c5 (/opt/atp/health_watchdog.sh).
#
# Scope: ONLY restarts automated-trading-platform-backend-aws-1 (never canary).
# No compose down, no trading executor changes, no live orders.
#
# Runbook: docs/runbooks/ATP_HEALTH_WATCHDOG.md
set -uo pipefail

REPO_ROOT="${ATP_REPO_ROOT:-/home/ubuntu/automated-trading-platform}"
STATE_FILE="${ATP_HEALTH_WATCHDOG_STATE:-/var/lib/atp/health_watchdog.state}"
LOG_FILE="${ATP_HEALTH_WATCHDOG_LOG:-/var/log/atp/health_watchdog.log}"
HEALTH_URL="${ATP_HEALTH_WATCHDOG_URL:-http://127.0.0.1:8002/api/health}"
CURL_TIMEOUT="${ATP_HEALTH_WATCHDOG_TIMEOUT_SEC:-5}"
CONSECUTIVE_FAILS="${ATP_HEALTH_WATCHDOG_CONSECUTIVE_FAILS:-2}"
GRACE_SEC="${ATP_HEALTH_WATCHDOG_GRACE_SEC:-600}"
COOLDOWN_SEC="${ATP_HEALTH_WATCHDOG_COOLDOWN_SEC:-900}"
MAX_RESTARTS_HOUR="${ATP_HEALTH_WATCHDOG_MAX_RESTARTS_HOUR:-2}"
PRIMARY_CONTAINER="${ATP_HEALTH_WATCHDOG_CONTAINER:-automated-trading-platform-backend-aws-1}"
DRY_RUN="${ATP_HEALTH_WATCHDOG_DRY_RUN:-0}"
TELEGRAM_ENABLED="${ATP_HEALTH_WATCHDOG_TELEGRAM:-1}"

now_epoch() {
  date +%s
}

log() {
  local msg="[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*"
  echo "$msg"
  if mkdir -p "$(dirname "$LOG_FILE")" 2>/dev/null; then
    echo "$msg" >>"$LOG_FILE" 2>/dev/null || true
  fi
}

load_telegram_env() {
  [ "$TELEGRAM_ENABLED" = "0" ] && return 0
  local f
  for f in ".env" ".env.aws" "secrets/runtime.env"; do
    if [ -f "$REPO_ROOT/$f" ]; then
      set +u
      # shellcheck source=/dev/null
      . "$REPO_ROOT/$f" 2>/dev/null || true
      set -u
    fi
  done
  [ -z "${TELEGRAM_CHAT_ID:-}" ] && [ -n "${TELEGRAM_CHAT_ID_AWS:-}" ] && TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID_AWS}"
  TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID_OPS:-${TELEGRAM_CHAT_ID:-}}"
  export TELEGRAM_CHAT_ID
}

resolve_telegram_token() {
  [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && return 0
  [ -z "${TELEGRAM_BOT_TOKEN_ENCRYPTED:-}" ] && return 1
  local tmpf
  tmpf="$(mktemp 2>/dev/null)" || return 1
  local ret=1
  if (cd "$REPO_ROOT" && python3 "$REPO_ROOT/scripts/diag/decrypt_telegram_token_for_alert.py" "$tmpf" 2>/dev/null) \
    && [ -s "$tmpf" ]; then
    TELEGRAM_BOT_TOKEN="$(cat "$tmpf")"
    export TELEGRAM_BOT_TOKEN
    ret=0
  fi
  rm -f "$tmpf" 2>/dev/null || true
  return "$ret"
}

notify_telegram() {
  local msg="$1"
  [ "$TELEGRAM_ENABLED" = "0" ] && return 0
  load_telegram_env
  resolve_telegram_token || {
    log "Telegram skipped (no token): $msg"
    return 0
  }
  if [ "$DRY_RUN" = "1" ]; then
    log "Telegram (dry run): $msg"
    return 0
  fi
  if [ -f "$REPO_ROOT/scripts/aws/_notify_telegram_fail.sh" ]; then
    bash "$REPO_ROOT/scripts/aws/_notify_telegram_fail.sh" "$msg" || true
  fi
}

read_state() {
  consecutive_fails=0
  last_restart_epoch=0
  restart_epochs=""
  if [ -f "$STATE_FILE" ]; then
    # shellcheck source=/dev/null
    . "$STATE_FILE" 2>/dev/null || true
  fi
  consecutive_fails="${consecutive_fails:-0}"
  last_restart_epoch="${last_restart_epoch:-0}"
  restart_epochs="${restart_epochs:-}"
}

write_state() {
  if ! mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null; then
    log "Warning: cannot write state file $STATE_FILE"
    return 0
  fi
  cat >"$STATE_FILE" <<EOF
consecutive_fails=${consecutive_fails}
last_restart_epoch=${last_restart_epoch}
restart_epochs=${restart_epochs}
EOF
}

restart_epochs_to_list() {
  restart_epoch_list=()
  [ -z "${restart_epochs:-}" ] && return 0
  local old_ifs="$IFS"
  IFS=','
  # shellcheck disable=SC2206
  restart_epoch_list=($restart_epochs)
  IFS="$old_ifs"
}

prune_restart_epochs() {
  local cutoff="$1"
  restart_epochs_to_list
  local kept="" epoch
  for epoch in "${restart_epoch_list[@]}"; do
    [ -z "$epoch" ] && continue
    if [ "$epoch" -ge "$cutoff" ]; then
      kept="${kept:+$kept,}$epoch"
    fi
  done
  restart_epochs="$kept"
}

count_restarts_last_hour() {
  local now="$1"
  prune_restart_epochs $((now - 3600))
  restart_epochs_to_list
  echo "${#restart_epoch_list[@]}"
}

assert_primary_container() {
  case "$PRIMARY_CONTAINER" in
    *canary*) log "Refusing restart: container name looks like canary ($PRIMARY_CONTAINER)"; exit 1 ;;
    automated-trading-platform-backend-aws-1) return 0 ;;
    *)
      log "Refusing restart: unexpected container ($PRIMARY_CONTAINER); expected automated-trading-platform-backend-aws-1"
      exit 1
      ;;
  esac
}

probe_health() {
  curl -sf -o /dev/null --connect-timeout "$CURL_TIMEOUT" --max-time "$CURL_TIMEOUT" "$HEALTH_URL" 2>/dev/null
}

restart_primary_backend() {
  assert_primary_container
  log "Restarting primary backend container: $PRIMARY_CONTAINER"
  if [ "$DRY_RUN" = "1" ]; then
    log "Dry run: would docker restart $PRIMARY_CONTAINER"
    return 0
  fi
  docker restart "$PRIMARY_CONTAINER" >/dev/null 2>&1
}

main() {
  local now fail_count restarts_in_hour
  now="$(now_epoch)"
  read_state

  if [ "$last_restart_epoch" -gt 0 ]; then
    local since_restart=$((now - last_restart_epoch))
    if [ "$since_restart" -lt "$GRACE_SEC" ]; then
      log "Grace period active (${since_restart}s < ${GRACE_SEC}s since last restart); skipping restart logic"
      if probe_health; then
        consecutive_fails=0
        write_state
      fi
      exit 0
    fi
  fi

  if probe_health; then
    if [ "$consecutive_fails" -gt 0 ]; then
      log "Health OK; clearing consecutive_fails (was $consecutive_fails)"
    fi
    consecutive_fails=0
    write_state
    exit 0
  fi

  consecutive_fails=$((consecutive_fails + 1))
  log "Health probe failed ($HEALTH_URL timeout ${CURL_TIMEOUT}s); consecutive_fails=$consecutive_fails"
  write_state

  if [ "$consecutive_fails" -lt "$CONSECUTIVE_FAILS" ]; then
    log "Waiting for ${CONSECUTIVE_FAILS} consecutive fails before action (need $((CONSECUTIVE_FAILS - consecutive_fails)) more)"
    exit 0
  fi

  if [ "$last_restart_epoch" -gt 0 ]; then
    local since_restart=$((now - last_restart_epoch))
    if [ "$since_restart" -lt "$COOLDOWN_SEC" ]; then
      log "Cooldown active (${since_restart}s < ${COOLDOWN_SEC}s); not restarting"
      exit 0
    fi
  fi

  restarts_in_hour="$(count_restarts_last_hour "$now")"
  if [ "$restarts_in_hour" -ge "$MAX_RESTARTS_HOUR" ]; then
    log "Max restarts/hour reached ($restarts_in_hour >= $MAX_RESTARTS_HOUR); skipping restart"
    notify_telegram "⚠️ ATP health watchdog: /api/health still failing after ${consecutive_fails} probes; max restarts/hour (${MAX_RESTARTS_HOUR}) reached — manual intervention required on $(hostname -s)."
    exit 0
  fi

  restart_primary_backend
  last_restart_epoch="$now"
  restart_epochs="${restart_epochs:+$restart_epochs,}$now"
  prune_restart_epochs $((now - 3600))
  consecutive_fails=0
  write_state

  notify_telegram "🔄 ATP health watchdog: restarted primary backend ($PRIMARY_CONTAINER) on $(hostname -s) after ${CONSECUTIVE_FAILS} consecutive /api/health probe failures (timeout ${CURL_TIMEOUT}s). Grace ${GRACE_SEC}s; cooldown ${COOLDOWN_SEC}s."
  log "Restart complete; grace ${GRACE_SEC}s, cooldown ${COOLDOWN_SEC}s"
}

main "$@"
