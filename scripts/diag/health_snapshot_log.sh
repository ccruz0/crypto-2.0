#!/usr/bin/env bash
# Append a one-line stability snapshot to /var/log/atp/health_snapshots.log.
# Run hourly (cron or systemd timer) to get a timeline when something drifts.
# Creates /var/log/atp if missing; requires write permission (often root).
# All numeric fields are numbers so the log is jq-friendly for analytics.
set -euo pipefail

LOG_FILE="${ATP_HEALTH_SNAPSHOT_LOG:-/var/log/atp/health_snapshots.log}"
BASE="${BASE:-${ATP_HEALTH_BASE:-http://127.0.0.1:8002}}"
REPO_ROOT="${ATP_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"

mkdir -p "$(dirname "$LOG_FILE")"

# Numeric: digits only, safe for --argjson
disk_pct="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}' 2>/dev/null | tr -dc '0-9' | head -c 3)"
[ -z "$disk_pct" ] && disk_pct="100"
# grep -c exits 1 when no match; avoid pipefail killing the script
unhealthy="$(docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | (grep -ci unhealthy 2>/dev/null || echo 0) | tr -dc '0-9')"
[ -z "$unhealthy" ] && unhealthy="0"

# Verify outcome: what ops considers OK (PASS / DEGRADED / FAIL)
tmp_exit=""
tmp_exit="$(mktemp 2>/dev/null)" || true
if [ -n "$tmp_exit" ] && [ -w "$tmp_exit" ]; then
  # Inner subshell must not inherit set -e so we always write exit code when verify returns non-zero
  verify_output="$(cd "$REPO_ROOT" && (set +e; ./scripts/selfheal/verify.sh 2>/dev/null; echo $? > "$tmp_exit") | cat)" || true
  verify_exit="$(cat "$tmp_exit" 2>/dev/null)" || verify_exit="0"
  rm -f "$tmp_exit"
else
  verify_output="$(cd "$REPO_ROOT" && ./scripts/selfheal/verify.sh 2>/dev/null)" || true
  verify_exit="0"
fi
verify_label="$(echo "$verify_output" | tail -n 1)"
[ -z "$verify_label" ] && verify_label="unknown"
verify_exit="$(echo "$verify_exit" | tr -dc '0-9')"
[ -z "$verify_exit" ] && verify_exit="0"

health_system="$(curl -sS --max-time 5 "$BASE/api/health/system" 2>/dev/null || echo "{}")"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# system: pass via file so long JSON never breaks shell/arg length
tmp_sys=""
tmp_sys="$(mktemp 2>/dev/null)" || true
if [ -n "$tmp_sys" ]; then
  printf '%s' "$health_system" | jq -c . 2>/dev/null > "$tmp_sys" || echo "{}" > "$tmp_sys"
fi

# One JSON line: all numbers numeric so jq analytics work (e.g. .[].disk_pct | add / length)
if command -v jq >/dev/null 2>&1 && [ -n "$tmp_sys" ] && [ -r "$tmp_sys" ]; then
  payload="$(jq -cn \
    --arg ts "$timestamp" \
    --argjson disk_pct "$disk_pct" \
    --argjson unhealthy "$unhealthy" \
    --argjson verify_exit "$verify_exit" \
    --arg verify_label "$verify_label" \
    --slurpfile sys "$tmp_sys" \
    '{ts:$ts, disk_pct:$disk_pct, unhealthy:$unhealthy, verify_exit:$verify_exit, verify_label:$verify_label, global_status:($sys[0].global_status // "unknown"), market_data_status:($sys[0].market_data.status // "unknown"), market_updater_status:($sys[0].market_updater.status // "unknown"), system:$sys[0]}')"
  echo "$payload" >> "$LOG_FILE"
  rm -f "$tmp_sys"
else
  echo "{\"ts\":\"$timestamp\",\"disk_pct\":$disk_pct,\"unhealthy\":$unhealthy,\"verify_exit\":$verify_exit,\"verify_label\":\"$verify_label\",\"global_status\":\"unknown\",\"market_data_status\":\"unknown\",\"market_updater_status\":\"unknown\",\"system\":{}}" >> "$LOG_FILE"
  [ -n "$tmp_sys" ] && rm -f "$tmp_sys"
fi
