#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8002}"

disk_use_pct() {
  df -P / | awk 'NR==2 {gsub("%","",$5); print $5}'
}

unhealthy_count() {
  docker ps --format '{{.Names}} {{.Status}}' | grep -i unhealthy | wc -l | tr -d ' '
}

curl_json() {
  curl -sS --max-time 5 "$1"
}

main() {
  local disk_pct unhealthy
  disk_pct="$(disk_use_pct || echo 100)"
  unhealthy="$(unhealthy_count || echo 0)"
  # Safe for [ ] numeric comparison: strip non-digits, default if empty
  disk_pct="${disk_pct//[^0-9]/}"
  [[ -z "$disk_pct" ]] && disk_pct=100
  unhealthy="${unhealthy//[^0-9]/}"
  [[ -z "$unhealthy" ]] && unhealthy=0

  local health system
  health="$(curl_json "$BASE/api/health" || echo '{}')"
  system="$(curl_json "$BASE/api/health/system" || echo '{}')"

  local api_ok db_status md_status mu_status sm_status
  api_ok="$(echo "$health" | jq -r '.status // empty' 2>/dev/null || true)"
  db_status="$(echo "$system" | jq -r '.db_status // empty' 2>/dev/null || true)"
  md_status="$(echo "$system" | jq -r '.market_data.status // empty' 2>/dev/null || true)"
  mu_status="$(echo "$system" | jq -r '.market_updater.status // empty' 2>/dev/null || true)"
  sm_status="$(echo "$system" | jq -r '.signal_monitor.status // empty' 2>/dev/null || true)"
  # Telegram and trade_system intentionally not required for PASS (can be disabled / FAIL by design)

  # Print evidence JSON (useful for logs)
  echo "$system" | jq -c '{
    timestamp, global_status, db_status,
    market_data, market_updater, signal_monitor, telegram, trade_system
  }' 2>/dev/null || true

  if [ "$disk_pct" -ge 90 ]; then
    echo "FAIL:DISK:${disk_pct}%"
    exit 2
  fi

  if [ "$unhealthy" -gt 0 ]; then
    echo "FAIL:CONTAINERS_UNHEALTHY:${unhealthy}"
    exit 3
  fi

  if [ "${api_ok:-}" != "ok" ]; then
    echo "FAIL:API_HEALTH:${api_ok:-missing}"
    exit 4
  fi

  if [ "${db_status:-}" != "up" ]; then
    echo "FAIL:DB:${db_status:-missing}"
    exit 5
  fi

  # PASS: both market_data and market_updater PASS
  # DEGRADED: market_data WARN but updater PASS (1–4 symbols fresh) — do not trigger heal
  if [ "${md_status:-}" = "PASS" ] && [ "${mu_status:-}" = "PASS" ]; then
    : # fall through to signal_monitor
  elif [ "${md_status:-}" = "WARN" ] && [ "${mu_status:-}" = "PASS" ]; then
    echo "DEGRADED:MARKET_DATA_WARN_UPDATER_PASS"
    exit 0
  fi
  if [ "${md_status:-}" != "PASS" ]; then
    echo "FAIL:MARKET_DATA:${md_status:-missing}"
    exit 6
  fi
  if [ "${mu_status:-}" != "PASS" ]; then
    echo "FAIL:MARKET_UPDATER:${mu_status:-missing}"
    exit 7
  fi

  if [ "${sm_status:-}" != "PASS" ]; then
    echo "FAIL:SIGNAL_MONITOR:${sm_status:-missing}"
    exit 8
  fi

  echo "PASS"
}

main "$@"
