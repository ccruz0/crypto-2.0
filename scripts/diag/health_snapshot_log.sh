#!/usr/bin/env bash
# Append a one-line stability snapshot to /var/log/atp/health_snapshots.log.
# Run hourly (cron or systemd timer) to get a timeline when something drifts.
# Creates /var/log/atp if missing; requires write permission (often root).
set -euo pipefail

LOG_FILE="${ATP_HEALTH_SNAPSHOT_LOG:-/var/log/atp/health_snapshots.log}"
BASE="${ATP_HEALTH_BASE:-http://127.0.0.1:8002}"

mkdir -p "$(dirname "$LOG_FILE")"

disk_pct="$(df -P / | awk 'NR==2 {gsub("%","",$5); print $5}' || echo "?")"
unhealthy="$(docker ps --format '{{.Names}} {{.Status}}' 2>/dev/null | grep -ci unhealthy || echo "0")"
health_system="$(curl -sS --max-time 5 "$BASE/api/health/system" 2>/dev/null || echo "{}")"
timestamp="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"

# One JSON line per run: ts, disk_pct, unhealthy, system (full payload)
if command -v jq >/dev/null 2>&1; then
  tmp="$(mktemp)"
  printf '%s' "$health_system" > "$tmp"
  jq -c -n \
    --arg ts "$timestamp" --arg disk "$disk_pct" --argjson un "$unhealthy" \
    --slurpfile sys "$tmp" \
    '{ts: $ts, disk_pct: $disk, unhealthy: $un, system: $sys[0]}' >> "$LOG_FILE"
  rm -f "$tmp"
else
  echo "{\"ts\":\"$timestamp\",\"disk_pct\":\"$disk_pct\",\"unhealthy\":$unhealthy,\"system\":$health_system}" >> "$LOG_FILE"
fi
