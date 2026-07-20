#!/usr/bin/env bash
# Run GitHub App cutover monitor, write logs, and send Telegram alerts on failure.
# Transient restart blips (health=starting) are rechecked once before paging.
# Success heartbeats at most once every 12 hours. Never prints secret values.
#
# Usage (from repo root or via cron):
#   bash scripts/aws/run_github_app_cutover_monitor_with_alerts.sh

set -uo pipefail
set +x 2>/dev/null || true

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

# shellcheck source=scripts/aws/_github_app_cutover_alert_lib.sh
source "$SCRIPT_DIR/_github_app_cutover_alert_lib.sh"

LOG_DIR="$ROOT_DIR/logs"
LATEST_LOG="$LOG_DIR/github_app_monitor_latest.log"
APPEND_LOG="$LOG_DIR/github_app_monitor.log"
LAST_SUCCESS_ALERT="$LOG_DIR/github_app_monitor_last_success_alert.txt"
PAT_REMOVAL_ALERT_MARKER="$LOG_DIR/github_app_pat_removal_ready_alert_sent"
OBSERVATION_END_UTC="2026-06-12 08:18:00"
HEARTBEAT_INTERVAL_S=$((12 * 60 * 60))
TRANSIENT_RECHECK_S="${TRANSIENT_RECHECK_S:-90}"

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

parse_monitor_fields() {
  local out="$1"
  HEALTH="$(echo "$out" | sed -n 's/^GITHUB_APP_CUTOVER_HEALTH=//p' | tail -1)"
  CUTOVER="$(echo "$out" | sed -n 's/^CUTOVER_READY=//p' | tail -1)"
  [[ -z "$CUTOVER" ]] && CUTOVER="$(echo "$out" | sed -n 's/^  parsed CUTOVER_READY: //p' | tail -1)"
  AUTH_MODE="$(echo "$out" | sed -n 's/^  parsed auth_mode: //p' | tail -1)"
  [[ -z "$AUTH_MODE" ]] && AUTH_MODE="$(echo "$out" | sed -n 's/^auth_mode: //p' | tail -1)"
  EXCHANGE_WARN="$(echo "$out" | sed -n 's/^EXCHANGE_CREDENTIAL_WARNINGS=//p' | tail -1)"
  MINT_OK=no
  if echo "$out" | grep -q 'live token mint: yes\|Live token mint succeeded'; then
    MINT_OK=yes
  fi
  MONITOR_FAILURES="$(extract_monitor_failures "$out")"
}

append_monitor_log() {
  local label="$1"
  local out="$2"
  {
    echo "=== GitHub App cutover monitor run: $label ==="
    echo "$out"
    echo
  } | tee "$LATEST_LOG" >> "$APPEND_LOG"
}

utc_now="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
utc_epoch="$(date -u +%s)"

MONITOR_OUT=""
MONITOR_EXIT=0
MONITOR_OUT="$(bash scripts/aws/monitor_github_app_cutover.sh 2>&1)" || MONITOR_EXIT=$?
append_monitor_log "$utc_now" "$MONITOR_OUT"

HEALTH="" CUTOVER="" AUTH_MODE="" EXCHANGE_WARN="" MINT_OK=no MONITOR_FAILURES=""
parse_monitor_fields "$MONITOR_OUT"

FAIL=no
FAIL_REASONS=()

[[ "$HEALTH" == "PASS" ]] || { FAIL=yes; FAIL_REASONS+=("GITHUB_APP_CUTOVER_HEALTH=${HEALTH:-unknown}"); }
[[ "$CUTOVER" == "YES" ]] || { FAIL=yes; FAIL_REASONS+=("CUTOVER_READY=${CUTOVER:-unknown}"); }
[[ "$AUTH_MODE" == "github_app" ]] || { FAIL=yes; FAIL_REASONS+=("auth_mode=${AUTH_MODE:-unknown}"); }

auth_hits="$(echo "$MONITOR_OUT" | grep -Ei 'failed to mint|GitHub API auth unavailable|auth_method=none|PermissionError' \
  | grep -Evi 'crypto\.com|EXCHANGE_CUSTOM|Exchange credential|GitHub auth diagnostics:' || true)"
if [[ -n "$auth_hits" ]]; then
  FAIL=yes
  FAIL_REASONS+=("GitHub auth error patterns in monitor output")
fi

echo "parsed GITHUB_APP_CUTOVER_HEALTH=${HEALTH:-unknown}"
echo "parsed CUTOVER_READY=${CUTOVER:-unknown}"
echo "parsed auth_mode=${AUTH_MODE:-unknown}"
echo "parsed EXCHANGE_CREDENTIAL_WARNINGS=${EXCHANGE_WARN:-unknown}"
echo "parsed live_token_mint=${MINT_OK}"

if [[ "$FAIL" == "yes" ]]; then
  SEVERITY="$(classify_failure "$AUTH_MODE" "$CUTOVER" "$MINT_OK" "$MONITOR_FAILURES")"
  echo "classified severity: $SEVERITY"

  # Transient restart blip: wait and recheck once before paging.
  if [[ "$SEVERITY" == "TRANSIENT" ]]; then
    echo "Transient failure detected; rechecking in ${TRANSIENT_RECHECK_S}s..."
    sleep "$TRANSIENT_RECHECK_S"
    RECHECK_NOW="$(date -u '+%Y-%m-%d %H:%M:%S UTC')"
    RECHECK_OUT=""
    RECHECK_EXIT=0
    RECHECK_OUT="$(bash scripts/aws/monitor_github_app_cutover.sh 2>&1)" || RECHECK_EXIT=$?
    append_monitor_log "$RECHECK_NOW (transient recheck)" "$RECHECK_OUT"

    parse_monitor_fields "$RECHECK_OUT"
    if [[ "$HEALTH" == "PASS" && "$CUTOVER" == "YES" && "$AUTH_MODE" == "github_app" ]]; then
      echo "Transient recheck PASS — suppressing Telegram alert."
      echo "Monitor failure reasons (initial, cleared): ${FAIL_REASONS[*]}"
      exit 0
    fi

    # Still failing — reclassify from recheck output
    FAIL_REASONS=("GITHUB_APP_CUTOVER_HEALTH=${HEALTH:-unknown}" "recheck_after_transient")
    [[ "$CUTOVER" == "YES" ]] || FAIL_REASONS+=("CUTOVER_READY=${CUTOVER:-unknown}")
    [[ "$AUTH_MODE" == "github_app" ]] || FAIL_REASONS+=("auth_mode=${AUTH_MODE:-unknown}")
    SEVERITY="$(classify_failure "$AUTH_MODE" "$CUTOVER" "$MINT_OK" "$MONITOR_FAILURES")"
    MONITOR_OUT="$RECHECK_OUT"
    echo "classified severity after recheck: $SEVERITY"
  fi

  FAILURES_BLOCK="none"
  if [[ -n "${MONITOR_FAILURES// }" ]]; then
    FAILURES_BLOCK="$(echo "$MONITOR_FAILURES" | sed 's/^/- /')"
  else
    FAILURES_BLOCK="$(printf '%s\n' "${FAIL_REASONS[@]}" | sed 's/^/- /')"
  fi

  REMEDY="$(remedy_for_class "$SEVERITY")"

  fail_msg="$(cat <<EOF
🚨 ATP GitHub App Cutover Alert

Severity: $SEVERITY
Time UTC: $(date -u '+%Y-%m-%d %H:%M:%S UTC')
auth_mode: ${AUTH_MODE:-unknown}
CUTOVER_READY: ${CUTOVER:-unknown}
GITHUB_APP_CUTOVER_HEALTH: ${HEALTH:-unknown}
live_token_mint: ${MINT_OK}

Investigation (failures):
$FAILURES_BLOCK

Remedy:
$REMEDY
EOF
)"
  if send_telegram "$fail_msg"; then
    echo "Telegram failure alert sent (severity=$SEVERITY)."
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
