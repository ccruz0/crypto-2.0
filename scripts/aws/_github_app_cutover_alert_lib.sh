#!/usr/bin/env bash
# Shared helpers for GitHub App cutover alert classification + infra auto-heal.
# Sourced by run_github_app_cutover_monitor_with_alerts.sh and tests.
# Never prints secret values.

# Extract bullet lines under "Failures:" from monitor output.
extract_monitor_failures() {
  local out="$1"
  echo "$out" | awk '
    /^Failures:/ { in_fail=1; next }
    in_fail && /^[[:space:]]*- / { sub(/^[[:space:]]*- /, ""); print; next }
    in_fail && NF == 0 { exit }
    in_fail && /^[A-Za-z]|EXCHANGE_CREDENTIAL|^GITHUB_APP/ { exit }
  '
}

# True when every non-empty failure line is restart/probe-style (infra), not auth.
failures_are_infra_only() {
  local failures_text="$1"
  local line found=no
  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    found=yes
    case "$line" in
      *"health starting"*|*"ping_fast not ok"*|*"health/ready not ready"*|*"not running"*|*"unhealthy"*|*"health=starting"*|*"health="*)
        ;;
      *"logs contain GitHub auth warnings"*)
        # Cutover mint already OK or backend down; usually diagnostic noise.
        ;;
      *"auth_mode is not github_app"*|*"CUTOVER_READY is not YES"*|*"live token mint not confirmed"*)
        # Cascade from a down backend (verify cannot read auth_mode / mint).
        # Treat as infra when auth_mode is unknown — see classify_failure.
        ;;
      *)
        return 1
        ;;
    esac
  done <<< "$failures_text"
  [[ "$found" == "yes" ]]
}

# Classify: TRANSIENT | AUTH | OTHER
# TRANSIENT = containers/probes not ready, OR auth_mode unknown because backend is down
#             (failure list is infra-only / cascade from down backend).
# AUTH      = real GitHub App cutover/mint breakage while we can observe auth state.
classify_failure() {
  local auth_mode="$1"
  local cutover="$2"
  local mint_ok="$3"
  local failures_text="$4"

  # Backend down / verify unreachable: auth_mode unknown + infra/cascade failures
  # must NOT page as AUTH (false positive that flooded ATP Control).
  if [[ "$auth_mode" == "unknown" || -z "$auth_mode" ]]; then
    if failures_are_infra_only "$failures_text" || [[ -z "${failures_text// }" ]]; then
      echo "TRANSIENT"
      return 0
    fi
  fi

  if [[ "$auth_mode" != "github_app" || "$cutover" != "YES" || "$mint_ok" != "yes" ]]; then
    echo "AUTH"
    return 0
  fi

  local line non_transient=no
  if [[ -z "${failures_text// }" ]]; then
    echo "OTHER"
    return 0
  fi

  while IFS= read -r line; do
    [[ -z "$line" ]] && continue
    case "$line" in
      *"health starting"*|*"ping_fast not ok"*|*"health/ready not ready"*|*"not running"*|*"unhealthy"*|*"health=starting"*)
        ;;
      *"logs contain GitHub auth warnings"*)
        # Cutover mint already OK; usually diagnostic noise or stale log lines.
        ;;
      *"auth_mode is not github_app"*|*"CUTOVER_READY is not YES"*|*"live token mint not confirmed"*)
        echo "AUTH"
        return 0
        ;;
      *)
        non_transient=yes
        ;;
    esac
  done <<< "$failures_text"

  if [[ "$non_transient" == "yes" ]]; then
    echo "OTHER"
  else
    echo "TRANSIENT"
  fi
}

# Disk used % on / (digits only). Empty on failure.
_cutover_disk_pct() {
  df -P / 2>/dev/null | awk 'NR==2 {gsub("%","",$5); print $5}'
}

# Volume-safe disk reclaim when root is critically full (no named-volume prune).
# Uses infra/cleanup_disk.sh + predeploy_disk_guard when available.
# Never prints secrets. Best-effort; always returns 0.
reclaim_disk_for_cutover_heal() {
  local root_dir="${1:-.}"
  local threshold="${GITHUB_APP_CUTOVER_DISK_RECLAIM_PCT:-90}"
  local pct

  pct="$(_cutover_disk_pct)"
  pct="${pct//[^0-9]/}"
  [[ -z "$pct" ]] && pct=100

  echo "auto-heal: disk_used=${pct}% (reclaim if >= ${threshold}%)"
  if [[ "$pct" -lt "$threshold" ]]; then
    return 0
  fi

  echo "auto-heal: disk critically full — reclaiming (volume-safe; no compose down)"
  if [[ -x "$root_dir/infra/cleanup_disk.sh" ]]; then
    bash "$root_dir/infra/cleanup_disk.sh" || true
  fi
  if [[ -x "$root_dir/scripts/aws/predeploy_disk_guard.sh" ]]; then
    # Force Tier 2 unused-image prune by setting a high MIN_FREE_GB floor.
    MIN_FREE_GB="${GITHUB_APP_CUTOVER_MIN_FREE_GB:-4}" \
      bash "$root_dir/scripts/aws/predeploy_disk_guard.sh" || true
  else
    docker builder prune -af 2>/dev/null || true
    docker image prune -af 2>/dev/null || true
    sudo find /var/lib/docker/containers/ -name "*-json.log" -type f \
      -exec truncate -s 0 {} \; 2>/dev/null || true
    sudo journalctl --vacuum-time=3d 2>/dev/null || true
  fi
  echo "auto-heal: disk after reclaim=$(_cutover_disk_pct)%"
  return 0
}

# Safe infra recovery for TRANSIENT cutover monitor failures.
# Order: disk reclaim (if full) → ensure_stack_up → targeted restart.
# Respects deploy marker and cooldown. Never prints secrets.
# Returns 0 if ping_fast is OK after attempt, 1 otherwise.
attempt_cutover_infra_auto_heal() {
  local root_dir="${1:-.}"
  local log_dir="${2:-$root_dir/logs}"
  local cooldown_file="${3:-$log_dir/github_app_cutover_auto_heal_last}"
  local cooldown_s="${GITHUB_APP_CUTOVER_AUTO_HEAL_COOLDOWN_S:-900}"
  local enabled="${GITHUB_APP_CUTOVER_AUTO_HEAL:-1}"
  local marker="${ATP_DEPLOY_MARKER:-/tmp/atp-deploy-in-progress}"
  local marker_ttl="${ATP_DEPLOY_MARKER_TTL_SECS:-1800}"
  local ping_url="${GITHUB_APP_CUTOVER_HEAL_PING_URL:-http://127.0.0.1:8002/ping_fast}"
  local now last elapsed epoch age
  local restart_err=""

  if [[ "$enabled" != "1" ]]; then
    echo "auto-heal skipped: GITHUB_APP_CUTOVER_AUTO_HEAL=$enabled"
    return 1
  fi

  mkdir -p "$log_dir" 2>/dev/null || true
  # If logs dir cannot be created (disk full), continue with /tmp cooldown.
  if [[ ! -d "$log_dir" ]]; then
    log_dir="/tmp"
    cooldown_file="/tmp/github_app_cutover_auto_heal_last"
  fi

  if [[ -f "$marker" ]]; then
    now="$(date +%s)"
    epoch="$(sed -n 's/.*epoch=\([0-9]\{1,\}\).*/\1/p' "$marker" 2>/dev/null | head -1)"
    if [[ -z "$epoch" ]]; then
      epoch="$(stat -c %Y "$marker" 2>/dev/null || echo 0)"
    fi
    age=$((now - epoch))
    if [[ "$age" -lt "$marker_ttl" ]]; then
      echo "auto-heal skipped: deploy in progress (marker age=${age}s)"
      return 1
    fi
    echo "auto-heal: clearing stale deploy marker (age=${age}s)"
    rm -f "$marker" 2>/dev/null || true
  fi

  if [[ -f "$cooldown_file" ]]; then
    last="$(cat "$cooldown_file" 2>/dev/null || echo 0)"
    now="$(date +%s)"
    # Support both epoch and human timestamps
    if [[ "$last" =~ ^[0-9]+$ ]]; then
      :
    else
      last="$(date -u -d "$last" +%s 2>/dev/null || echo 0)"
    fi
    elapsed=$((now - last))
    if [[ "$elapsed" -lt "$cooldown_s" ]]; then
      echo "auto-heal skipped: cooldown (${elapsed}s < ${cooldown_s}s)"
      return 1
    fi
  fi

  date +%s >"$cooldown_file" 2>/dev/null || true
  echo "auto-heal: starting infra recovery (disk reclaim → ensure_stack_up → restart)"

  # Disk full makes compose up / restart fail with "no space left on device".
  reclaim_disk_for_cutover_heal "$root_dir"

  if [[ -x "$root_dir/scripts/aws/ensure_stack_up.sh" ]]; then
    # Shorter wait for hourly monitor context (overrideable).
    ENSURE_STACK_WAIT_ITERS="${ENSURE_STACK_WAIT_ITERS:-18}" \
    ENSURE_STACK_WAIT_INTERVAL="${ENSURE_STACK_WAIT_INTERVAL:-5}" \
      bash "$root_dir/scripts/aws/ensure_stack_up.sh" || true
  else
    echo "auto-heal: ensure_stack_up.sh missing"
  fi

  if curl -fsS --connect-timeout 5 --max-time 8 "$ping_url" >/dev/null 2>&1; then
    echo "auto-heal: ping_fast OK after ensure_stack_up"
    return 0
  fi

  echo "auto-heal: ping still failing — restarting backend-aws"
  restart_err="$(
    cd "$root_dir" || exit 1
    if [[ -x scripts/aws/prod_compose.sh ]]; then
      bash scripts/aws/prod_compose.sh restart backend-aws 2>&1 || \
        docker compose --profile aws restart backend-aws 2>&1 || true
    else
      docker compose --profile aws restart backend-aws 2>&1 || true
    fi
  )" || true
  if [[ -n "$restart_err" ]]; then
    echo "$restart_err" | tail -20 | sed 's/^/  /'
  fi
  if echo "$restart_err" | grep -qi 'no space left on device'; then
    echo "auto-heal: restart hit ENOSPC — reclaiming disk again then retry restart"
    reclaim_disk_for_cutover_heal "$root_dir"
    (
      cd "$root_dir" || exit 1
      docker compose --profile aws restart backend-aws 2>&1 || true
    ) | tail -10 | sed 's/^/  /' || true
  fi

  local i
  for i in $(seq 1 24); do
    if curl -fsS --connect-timeout 5 --max-time 8 "$ping_url" >/dev/null 2>&1; then
      echo "auto-heal: ping_fast OK after backend-aws restart (~$((i * 5))s)"
      return 0
    fi
    sleep 5
  done

  echo "auto-heal: still unhealthy after recovery attempt (disk=$(_cutover_disk_pct)%)"
  return 1
}

remedy_for_class() {
  local class="$1"
  case "$class" in
    TRANSIENT)
      cat <<'EOF'
Containers were restarting or not ready (or backend down made auth_mode look unknown).
Auto-heal already tried disk reclaim + ensure_stack_up / backend-aws restart when enabled.
If this persists — especially "no space left on device":
  df -h /
  bash infra/cleanup_disk.sh
  bash scripts/aws/predeploy_disk_guard.sh
  bash scripts/aws/ensure_stack_up.sh
  docker compose --profile aws restart backend-aws
  docker compose --profile aws logs backend-aws --tail=80
EOF
      ;;
    AUTH)
      cat <<'EOF'
GitHub App auth is broken or not cut over.
On PROD:
  bash scripts/aws/verify_github_app_cutover_ready.sh
  bash scripts/aws/monitor_github_app_cutover.sh
Check SSM params under /automated-trading-platform/prod/github_app/
and container env (GITHUB_APP_ID / INSTALLATION_ID / PRIVATE_KEY_B64).
EOF
      ;;
    *)
      cat <<'EOF'
Investigate on PROD:
  cd /home/ubuntu/crypto-2.0
  bash scripts/aws/monitor_github_app_cutover.sh
  tail -120 logs/github_app_monitor_latest.log
EOF
      ;;
  esac
}
