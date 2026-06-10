#!/usr/bin/env bash
# Run GitHub App cutover monitor, write logs, and send Telegram alerts on failure.
# Success heartbeats at most once every 12 hours. Never prints secret values.
#
# Usage (from repo root or via cron):
#   bash scripts/aws/run_github_app_cutover_monitor_with_alerts.sh

set -uo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

LOG_DIR="$ROOT_DIR/logs"
LATEST_LOG="$LOG_DIR/github_app_monitor_latest.log"
APPEND_LOG="$LOG_DIR/github_app_monitor.log"
LAST_SUCCESS_ALERT="$LOG_DIR/github_app_monitor_last_success_alert.txt"
PAT_REMOVAL_ALERT_MARKER="$LOG_DIR/github_app_pat_removal_ready_alert_sent"
OBSERVATION_END_UTC="2026-06-12 08:18:00"
HEARTBEAT_INTERVAL_S=$((12 * 60 * 60))

mkdir -p "$LOG_DIR"

read_runtime_key() {
  local key="$1"
  local val=""
  if [[ -r secrets/runtime.env ]]; then
    val="$(grep -m1 "^${key}=" secrets/runtime.env 2>/dev/null | cut -d= -f2- || true)"
  else
    val="$(sudo grep -m1 "^${key}=" secrets/runtime.env 2>/dev/null | cut -d= -f2- || true)"
  fi
  printf '%s' "$val"
}

send_telegram() {
  local text="$1"
  local token chat_id

  token="$(read_runtime_key TELEGRAM_BOT_TOKEN)"
  chat_id="$(read_runtime_key TELEGRAM_CHAT_ID)"

  if [[ -z "$token" || -z "$chat_id" ]]; then
    echo "Telegram alert skipped: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing"
    return 1
  fi

  if curl -sf -o /dev/null --connect-timeout 10 --max-time 20 \
    -X POST "https://api.telegram.org/bot${token}/sendMessage" \
    -d "chat_id=${chat_id}" \
    --data-urlencode "text=${text}" \
    -d "disable_web_page_preview=1" \
    2>/dev/null; then
    return 0
  fi
  echo "Telegram alert delivery failed (HTTP error)"
  return 1
}

utc_now="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
utc_epoch="$(date -u +%s)"

MONITOR_OUT=""
MONITOR_EXIT=0
MONITOR_OUT="$(bash scripts/aws/monitor_github_app_cutover.sh 2>&1)" || MONITOR_EXIT=$?

{
  echo "=== GitHub App cutover monitor run: $utc_now ==="
  echo "$MONITOR_OUT"
  echo
} | tee "$LATEST_LOG" >> "$APPEND_LOG"

HEALTH="$(echo "$MONITOR_OUT" | sed -n 's/^GITHUB_APP_CUTOVER_HEALTH=//p' | tail -1)"
CUTOVER="$(echo "$MONITOR_OUT" | sed -n 's/^CUTOVER_READY=//p' | tail -1)"
[[ -z "$CUTOVER" ]] && CUTOVER="$(echo "$MONITOR_OUT" | sed -n 's/^  parsed CUTOVER_READY: //p' | tail -1)"
AUTH_MODE="$(echo "$MONITOR_OUT" | sed -n 's/^  parsed auth_mode: //p' | tail -1)"
[[ -z "$AUTH_MODE" ]] && AUTH_MODE="$(echo "$MONITOR_OUT" | sed -n 's/^auth_mode: //p' | tail -1)"
EXCHANGE_WARN="$(echo "$MONITOR_OUT" | sed -n 's/^EXCHANGE_CREDENTIAL_WARNINGS=//p' | tail -1)"

FAIL=no
FAIL_REASONS=()

[[ "$HEALTH" == "PASS" ]] || { FAIL=yes; FAIL_REASONS+=("GITHUB_APP_CUTOVER_HEALTH=${HEALTH:-unknown}"); }
[[ "$CUTOVER" == "YES" ]] || { FAIL=yes; FAIL_REASONS+=("CUTOVER_READY=${CUTOVER:-unknown}"); }
[[ "$AUTH_MODE" == "github_app" ]] || { FAIL=yes; FAIL_REASONS+=("auth_mode=${AUTH_MODE:-unknown}"); }

auth_hits="$(echo "$MONITOR_OUT" | grep -Ei 'failed to mint|GitHub API auth unavailable|auth_method=none|PermissionError' \
  | grep -Evi 'crypto\.com|EXCHANGE_CUSTOM|Exchange credential' || true)"
if [[ -n "$auth_hits" ]]; then
  FAIL=yes
  FAIL_REASONS+=("GitHub auth error patterns in monitor output")
fi

echo "parsed GITHUB_APP_CUTOVER_HEALTH=${HEALTH:-unknown}"
echo "parsed CUTOVER_READY=${CUTOVER:-unknown}"
echo "parsed auth_mode=${AUTH_MODE:-unknown}"
echo "parsed EXCHANGE_CREDENTIAL_WARNINGS=${EXCHANGE_WARN:-unknown}"

if [[ "$FAIL" == "yes" ]]; then
  fail_msg="$(cat <<EOF
🚨 ATP GitHub App Cutover Alert

Status: FAIL
Time UTC: $utc_now
auth_mode: ${AUTH_MODE:-unknown}
CUTOVER_READY: ${CUTOVER:-unknown}
GITHUB_APP_CUTOVER_HEALTH: ${HEALTH:-unknown}

Action:
Run:
cd /home/ubuntu/crypto-2.0
bash scripts/aws/monitor_github_app_cutover.sh
EOF
)"
  if send_telegram "$fail_msg"; then
    echo "Telegram failure alert sent."
  fi
  echo "Monitor failure reasons: ${FAIL_REASONS[*]}"
  exit 1
fi

observation_end_epoch="$(date -u -d "$OBSERVATION_END_UTC" +%s 2>/dev/null || date -u -j -f '%Y-%m-%d %H:%M:%S' "$OBSERVATION_END_UTC" +%s 2>/dev/null || echo 0)"

if [[ "$observation_end_epoch" -gt 0 && "$utc_epoch" -ge "$observation_end_epoch" ]]; then
  if [[ ! -f "$PAT_REMOVAL_ALERT_MARKER" ]]; then
    pat_msg="$(cat <<EOF
✅ GitHub App observation window complete

Current status: PASS
auth_mode: github_app
CUTOVER_READY: YES

Next manual step:
cd /home/ubuntu/crypto-2.0
CONFIRM_REMOVE_LEGACY_PAT=yes bash scripts/aws/finalize_github_app_pat_removal.sh

Do not remove PAT unless you are ready to proceed.
EOF
)"
    if send_telegram "$pat_msg"; then
      date -u '+%Y-%m-%d %H:%M:%S UTC' > "$PAT_REMOVAL_ALERT_MARKER"
      echo "Telegram PAT-removal-ready alert sent (once)."
    else
      echo "Telegram PAT-removal-ready alert skipped or failed."
    fi
  else
    echo "Telegram PAT-removal-ready alert already sent (skipping)."
  fi
  exit 0
fi

send_heartbeat=no
if [[ ! -f "$LAST_SUCCESS_ALERT" ]]; then
  send_heartbeat=yes
else
  last_epoch="$(date -u -d "$(cat "$LAST_SUCCESS_ALERT" 2>/dev/null | head -1)" +%s 2>/dev/null || echo 0)"
  if [[ "$last_epoch" -eq 0 ]] || (( utc_epoch - last_epoch >= HEARTBEAT_INTERVAL_S )); then
    send_heartbeat=yes
  fi
fi

if [[ "$send_heartbeat" == "yes" ]]; then
  heartbeat_msg="$(cat <<EOF
✅ ATP GitHub App Cutover OK

Time UTC: $utc_now
auth_mode: github_app
CUTOVER_READY: YES
GITHUB_APP_CUTOVER_HEALTH: PASS

Observation window:
Still active until 2026-06-12 08:18 UTC
EOF
)"
  if send_telegram "$heartbeat_msg"; then
    date -u '+%Y-%m-%d %H:%M:%S UTC' > "$LAST_SUCCESS_ALERT"
    echo "Telegram success heartbeat sent."
  else
    echo "Telegram success heartbeat skipped or failed."
  fi
else
  echo "Telegram success heartbeat skipped (sent within last 12h)."
fi

exit 0
