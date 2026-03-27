#!/usr/bin/env bash
# OpenClaw LAB repair — run on the LAB EC2 instance (SSM Run Command runs as root).
# Does not touch PROD nginx. Verifies Docker, starts/restarts OpenClaw, checks :8080 + local curl.
#
# Usage (from SSM):  bash /home/ubuntu/crypto-2.0/scripts/openclaw/repair_openclaw_lab_on_instance.sh
# Env (optional):
#   ATP_REPO_PATH   — force repo root (default: detect)
#   OPENCLAW_PORT   — host port (default: 8080)
#   SKIP_SYSTEMD    — if 1, skip systemctl and use compose/docker only
#   OPENCLAW_LAB_DOCKER_PRUNE=1 — run `docker image prune -af` before compose (frees disk; removes unused images)
set -euo pipefail

OPENCLAW_PORT="${OPENCLAW_PORT:-8080}"
SKIP_SYSTEMD="${SKIP_SYSTEMD:-0}"

log() { echo "[openclaw-lab-repair] $*"; }
fail() { log "FAIL: $*"; echo "OPENCLAW_LAB_REPAIR_EXIT=1"; exit 1; }
ok() { log "OK: $*"; }

REPO=""
COMPOSE_REL="docker-compose.openclaw.yml"
COMPOSE_ALT="docker-compose.openclaw.yaml"

compose_basename() {
  if [[ -f "$REPO/$COMPOSE_REL" ]]; then echo "$COMPOSE_REL"; return 0; fi
  if [[ -f "$REPO/$COMPOSE_ALT" ]]; then echo "$COMPOSE_ALT"; return 0; fi
  return 1
}

detect_repo() {
  local c found name
  if [[ -n "${ATP_REPO_PATH:-}" ]]; then
    if [[ -f "$ATP_REPO_PATH/$COMPOSE_REL" || -f "$ATP_REPO_PATH/$COMPOSE_ALT" ]]; then
      REPO="$ATP_REPO_PATH"
      return 0
    fi
  fi
  for c in \
    "/home/ubuntu/crypto-2.0" \
    "/home/ubuntu/crypto-2.0" \
    "$HOME/automated-trading-platform"; do
    if [[ -f "$c/$COMPOSE_REL" || -f "$c/$COMPOSE_ALT" ]]; then
      REPO="$c"
      return 0
    fi
  done
  for name in "$COMPOSE_REL" "$COMPOSE_ALT"; do
    found="$(find /home/ubuntu -maxdepth 5 -name "$name" -type f 2>/dev/null | head -1 || true)"
    if [[ -n "$found" ]]; then
      REPO="$(cd "$(dirname "$found")" && pwd)"
      return 0
    fi
  done
  return 1
}

docker_check() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "docker CLI not installed"
  fi
  if ! docker info >/dev/null 2>&1; then
    fail "docker daemon not reachable (permission or docker not running). As root this usually means: sudo systemctl start docker"
  fi
  ok "Docker daemon reachable ($(docker info --format '{{.ServerVersion}}' 2>/dev/null || echo unknown))"
}

disk_report() {
  echo "--- df -h / /var/lib/docker  ---"
  df -h / 2>/dev/null || true
  df -h /var/lib/docker 2>/dev/null || true
}

maybe_prune_images() {
  if [[ "${OPENCLAW_LAB_DOCKER_PRUNE:-0}" != "1" ]]; then
    return 0
  fi
  log "OPENCLAW_LAB_DOCKER_PRUNE=1: docker image prune -af"
  docker image prune -af 2>/dev/null || true
}

compose_file() {
  local bn
  if [[ -n "${COMPOSE_FILE_OVERRIDE:-}" && -f "$COMPOSE_FILE_OVERRIDE" ]]; then
    echo "$COMPOSE_FILE_OVERRIDE"
    return 0
  fi
  if [[ -n "$REPO" ]] && bn="$(compose_basename)"; then
    echo "$REPO/$bn"
    return 0
  fi
  return 1
}

container_running() {
  docker ps --format '{{.Names}}' 2>/dev/null | grep -qi '^openclaw$' || \
    docker ps --format '{{.Names}}' 2>/dev/null | grep -qi openclaw
}

show_port_listeners() {
  ss -lntp 2>/dev/null | grep -E ":${OPENCLAW_PORT}\\b" || true
  netstat -lntp 2>/dev/null | grep -E ":${OPENCLAW_PORT}\\b" || true
}

has_port_listener() {
  ss -lntp 2>/dev/null | grep -qE ":${OPENCLAW_PORT}\\b" && return 0
  netstat -lntp 2>/dev/null | grep -qE ":${OPENCLAW_PORT}\\b" && return 0
  return 1
}

curl_local_ok() {
  local out
  out="$(curl -sS -I --max-time 8 "http://127.0.0.1:${OPENCLAW_PORT}/" 2>&1)" || return 1
  echo "$out" | head -20
  if echo "$out" | grep -qiE '^HTTP/[0-9]'; then
    return 0
  fi
  return 1
}

method_used="unknown"

start_via_systemd() {
  if [[ "$SKIP_SYSTEMD" == "1" ]]; then
    return 1
  fi
  if [[ ! -f /etc/systemd/system/openclaw.service ]]; then
    return 1
  fi
  log "Trying systemd: openclaw.service"
  if systemctl restart openclaw; then
    method_used="systemd:openclaw.service"
    return 0
  fi
  log "systemctl restart openclaw failed (ubuntu docker group?). Will try compose as root."
  return 1
}

start_via_compose() {
  local cf img hb
  cf="$(compose_file)" || fail "No $COMPOSE_REL found under detected repo"
  # SSM agent IPC can time out if this function produces no stdout for ~90–120s (e.g. long docker pull).
  ( while sleep 20; do echo "[openclaw-lab-repair] compose pull/build still running..."; done ) &
  hb=$!
  trap 'kill "$hb" 2>/dev/null || true' RETURN
  mkdir -p "$REPO/secrets" /opt/openclaw/home-data 2>/dev/null || true
  touch "$REPO/secrets/runtime.env" 2>/dev/null || true
  mkdir -p /home/ubuntu/secrets 2>/dev/null || true
  touch /home/ubuntu/secrets/openclaw_token 2>/dev/null || true
  chmod 600 /home/ubuntu/secrets/openclaw_token 2>/dev/null || true
  chown -R ubuntu:ubuntu "$REPO" /opt/openclaw /home/ubuntu/secrets 2>/dev/null || true

  img="${OPENCLAW_REPAIR_IMAGE:-ghcr.io/ccruz0/openclaw:latest}"
  log "Compose: pull service openclaw then up --no-build (image=$img) file=$cf"
  # Pull streams huge progress lines; SSM Run Command can hit IPC timeouts if we write it all to the session pipe.
  local clog=/tmp/openclaw-lab-compose-repair.log
  : >"$clog"
  if ! (
    cd "$REPO" && OPENCLAW_IMAGE="$img" docker compose -p openclaw-lab -f "$cf" pull openclaw >>"$clog" 2>&1 &&
    OPENCLAW_IMAGE="$img" docker compose -p openclaw-lab -f "$cf" up -d --no-build >>"$clog" 2>&1
  ); then
    log "Quick compose (prebuilt image) failed; trying full build + up (slow; logs: $clog)"
    tail -40 "$clog" || true
    if ! (cd "$REPO" && docker compose -p openclaw-lab -f "$cf" up -d >>"$clog" 2>&1); then
      tail -80 "$clog" || true
      if grep -qi 'no space left on device' "$clog" 2>/dev/null; then
        log "Disk full while pulling/building. Free space (df), run docker image prune / system prune, or grow the LAB EBS volume. Re-run with OPENCLAW_LAB_DOCKER_PRUNE=1 after backup if safe."
      fi
      return 1
    fi
    method_used="docker_compose:$cf (full build)"
  else
    method_used="docker_compose:$cf (image $img)"
  fi
  echo "--- tail $clog ---"
  tail -40 "$clog" || true
  docker compose -p openclaw-lab -f "$cf" ps -a 2>/dev/null || true
}

start_via_docker_start() {
  if docker ps -a --format '{{.Names}}' 2>/dev/null | grep -qi '^openclaw$'; then
    log "Starting existing container name=openclaw"
    docker start openclaw
    method_used="docker_start:openclaw"
    return 0
  fi
  return 1
}

echo "======== OpenClaw LAB repair ========="
echo "HOST=$(hostname -f 2>/dev/null || hostname) DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)"

docker_check
disk_report
maybe_prune_images

if detect_repo; then
  ok "Repo root: $REPO"
else
  REPO="/home/ubuntu/crypto-2.0"
  log "WARN: could not auto-detect repo with $COMPOSE_REL; using default $REPO"
fi

if ! compose_file >/dev/null; then
  log "WARN: $COMPOSE_REL not found at $REPO — systemd/docker name openclaw only"
fi

echo "--- Before: docker ps (openclaw) ---"
docker ps -a --filter name=openclaw --no-trunc 2>/dev/null || true
echo "--- Before: listeners :${OPENCLAW_PORT} ---"
show_port_listeners

need_start=1
if container_running && has_port_listener; then
  if curl -sS -I --max-time 5 "http://127.0.0.1:${OPENCLAW_PORT}/" 2>/dev/null | grep -qiE '^HTTP/'; then
    ok "Already healthy (container + listener + HTTP on :${OPENCLAW_PORT})"
    method_used="already_running"
    need_start=0
  else
    log "Container up but HTTP check failed — will restart stack"
  fi
fi

if [[ "$need_start" -eq 1 ]]; then
  log "Repair: restart or start OpenClaw"
  if start_via_systemd; then
    :
  elif compose_file >/dev/null && start_via_compose; then
    :
  elif start_via_docker_start; then
    :
  else
    fail "No working start path (systemd, compose file, or stopped container openclaw)"
  fi
  log "Waiting for listener on :${OPENCLAW_PORT} (compose pull/build can take several minutes)..."
  waited=0
  while [[ "$waited" -lt 360 ]]; do
    has_port_listener && break
    echo "[openclaw-lab-repair] waiting for :${OPENCLAW_PORT} (${waited}s)..."
    sleep 5
    waited=$((waited + 5))
  done
fi

echo "--- After: docker ps (openclaw) ---"
docker ps -a --filter name=openclaw --no-trunc 2>/dev/null || true
echo "--- After: listeners :${OPENCLAW_PORT} ---"
show_port_listeners
if ! has_port_listener; then
  echo "--- docker logs openclaw (tail 60) ---"
  docker logs openclaw --tail 60 2>&1 || true
  fail "Nothing listening on TCP ${OPENCLAW_PORT} (service down or wrong port mapping)"
fi
ok "Port ${OPENCLAW_PORT} is listening"

echo "--- curl -I http://127.0.0.1:${OPENCLAW_PORT}/ ---"
if ! curl_local_ok; then
  echo "--- docker logs openclaw (tail 80) ---"
  docker logs openclaw --tail 80 2>&1 || true
  fail "curl to 127.0.0.1:${OPENCLAW_PORT} did not return HTTP headers"
fi
ok "Local HTTP response OK (any 2xx/3xx/401 counts)"

echo "--- Evidence summary ---"
echo "METHOD_USED=$method_used"
echo "REPO=${REPO:-}"
echo "COMPOSE=$(compose_file 2>/dev/null || echo n/a)"
systemctl is-active openclaw 2>/dev/null || true
echo "OPENCLAW_LAB_REPAIR_EXIT=0"
exit 0
