#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Idempotent production stack reconciliation / recovery.
#
# GUARANTEE: this script NEVER runs `docker compose down`. It only brings the
# aws-profile stack UP. It is therefore safe to run:
#   - at the end of a deploy (belt-and-suspenders),
#   - as an independent recovery SSM command after the main deploy command
#     fails, times out, is cancelled, or the SSM worker crashes,
#   - repeatedly (idempotent), after an interrupted/partial deploy,
#   - after a GitHub Actions retry or SSM reconnect.
#
# It exists specifically to eliminate the failure mode where a deploy was
# interrupted between `compose down` and `compose up -d`, leaving nginx alive
# but the backend stack absent (502/503). With this script as a recovery net,
# any interruption converges back to "stack running".
#
# Output: human-readable state + a recommended manual recovery command on
# failure. Never prints secrets.
# ---------------------------------------------------------------------------
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

BASE="${ENSURE_STACK_BASE:-http://127.0.0.1:8002}"
HEALTH_PATH="${ENSURE_STACK_HEALTH_PATH:-/ping_fast}"
MARKER="${ATP_DEPLOY_MARKER:-/tmp/atp-deploy-in-progress}"
MARKER_TTL="${ATP_DEPLOY_MARKER_TTL_SECS:-1800}"
WAIT_ITERS="${ENSURE_STACK_WAIT_ITERS:-30}"
WAIT_INTERVAL="${ENSURE_STACK_WAIT_INTERVAL:-5}"
# Initial probe retries so a momentary blip (e.g. gunicorn max_requests recycle)
# does not trigger an unnecessary recreate of a stack that is actually serving.
PROBE_RETRIES="${ENSURE_STACK_PROBE_RETRIES:-3}"
PROBE_INTERVAL="${ENSURE_STACK_PROBE_INTERVAL:-3}"
# Serialize with self-heal (scripts/selfheal/heal.sh uses the same lock) so two
# `docker compose up -d` invocations cannot race. Recovery must not block forever.
LOCK="${ATP_SELFHEAL_LOCK:-/var/lock/atp-selfheal.lock}"
LOCK_WAIT="${ATP_ENSURE_LOCK_WAIT_SECS:-60}"

COMPOSE=(bash "$ROOT_DIR/scripts/aws/prod_compose.sh")
RECOVERY_CMD="cd $ROOT_DIR && bash scripts/aws/ensure_stack_up.sh"

log() { echo "[ensure_stack_up] $*"; }

backend_healthy() {
  curl -fsS --connect-timeout 5 --max-time 8 "${BASE}${HEALTH_PATH}" >/dev/null 2>&1
}

# Healthy if any of PROBE_RETRIES attempts succeed (tolerates transient blips).
backend_healthy_retry() {
  local n
  for n in $(seq 1 "$PROBE_RETRIES"); do
    backend_healthy && return 0
    [ "$n" -lt "$PROBE_RETRIES" ] && sleep "$PROBE_INTERVAL"
  done
  return 1
}

# Remove the deploy marker only when it is stale (older than TTL). A fresh
# marker means a real deploy is in progress, so we leave it alone.
clear_stale_marker() {
  [ -f "$MARKER" ] || return 0
  local now epoch age
  now="$(date +%s)"
  epoch="$(sed -n 's/.*epoch=\([0-9]\{1,\}\).*/\1/p' "$MARKER" 2>/dev/null | head -1)"
  if [ -z "$epoch" ]; then
    epoch="$(stat -c %Y "$MARKER" 2>/dev/null || echo 0)"
  fi
  age=$((now - epoch))
  if [ "$age" -ge "$MARKER_TTL" ]; then
    rm -f "$MARKER" 2>/dev/null || true
    log "cleared stale deploy marker (age=${age}s >= ttl=${MARKER_TTL}s)"
  else
    log "deploy marker present but fresh (age=${age}s < ttl=${MARKER_TTL}s); leaving in place"
  fi
}

report_state() {
  log "container state:"
  "${COMPOSE[@]}" ps 2>/dev/null || docker ps --format 'table {{.Names}}\t{{.Status}}' 2>/dev/null || true
}

main() {
  log "start $(date -Is) (repo=$ROOT_DIR, health=${BASE}${HEALTH_PATH})"

  if [ ! -f "$ROOT_DIR/docker-compose.yml" ]; then
    log "ERROR: docker-compose.yml not found at $ROOT_DIR"
    log "RECOMMENDED_RECOVERY: $RECOVERY_CMD"
    exit 1
  fi

  # Best-effort: make sure compose has the secrets/fingerprint it needs. Never fatal.
  if [ -x "$ROOT_DIR/scripts/aws/render_runtime_env.sh" ]; then
    bash "$ROOT_DIR/scripts/aws/render_runtime_env.sh" >/dev/null 2>&1 \
      && log "secrets/runtime.env rendered" \
      || log "WARN: render_runtime_env failed; using existing secrets/runtime.env"
  fi
  if [ -x "$ROOT_DIR/scripts/aws/export_build_fingerprint.sh" ]; then
    bash "$ROOT_DIR/scripts/aws/export_build_fingerprint.sh" >/dev/null 2>&1 || true
  fi

  if backend_healthy_retry; then
    log "backend already healthy (${HEALTH_PATH}); stack is serving — no action needed"
    clear_stale_marker
    report_state
    log "RESULT: HEALTHY (no-op)"
    exit 0
  fi

  # Acquire the self-heal lock (best effort) so we don't race a concurrent
  # self-heal `up -d`. Proceed after LOCK_WAIT if it can't be acquired —
  # recovery is more important than perfect mutual exclusion.
  exec 8>"$LOCK" 2>/dev/null || true
  if command -v flock >/dev/null 2>&1; then
    if flock -w "$LOCK_WAIT" 8 2>/dev/null; then
      log "acquired recovery lock ($LOCK)"
    else
      log "WARN: could not acquire lock within ${LOCK_WAIT}s; proceeding anyway"
    fi
  fi

  log "backend NOT responding on ${HEALTH_PATH} — reconciling stack UP (no 'compose down')"

  # `up -d` recreates only missing/changed containers and leaves the rest
  # running. If images are missing it will build them. This is the recovery.
  if ! "${COMPOSE[@]}" up -d --remove-orphans; then
    log "ERROR: 'docker compose --profile aws up -d' failed"
    report_state
    log "CURRENT_STATE: backend unavailable; compose up failed"
    log "RECOMMENDED_RECOVERY: $RECOVERY_CMD"
    exit 1
  fi

  log "waiting up to $((WAIT_ITERS * WAIT_INTERVAL))s for backend health..."
  local i
  for i in $(seq 1 "$WAIT_ITERS"); do
    if backend_healthy; then
      log "backend healthy after ~$((i * WAIT_INTERVAL))s"
      break
    fi
    sleep "$WAIT_INTERVAL"
  done

  clear_stale_marker
  report_state

  if backend_healthy; then
    log "RESULT: HEALTHY (recovered)"
    exit 0
  fi

  log "RESULT: UNHEALTHY — stack brought up but backend not yet responding"
  log "CURRENT_STATE: containers started; ${HEALTH_PATH} not 200 yet (may still be warming, or a real fault)"
  log "RECOMMENDED_RECOVERY: $RECOVERY_CMD   # re-run; if it persists, check: ${COMPOSE[*]} logs backend-aws --tail 120"
  exit 1
}

main "$@"
