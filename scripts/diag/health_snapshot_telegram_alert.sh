#!/usr/bin/env bash
# Production-safe Telegram alert for health snapshot failures.
# Reads last N lines from health_snapshots.log; if rule triggers, send one message and cooldown.
# Exit 0 always. No hardcoded secrets; token/chat_id from env files.
set -uo pipefail

REPO_ROOT="${ATP_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="${ATP_HEALTH_SNAPSHOT_LOG:-/var/log/atp/health_snapshots.log}"
N="${ATP_ALERT_LINES:-5000}"
COOLDOWN_MINS="${ATP_ALERT_COOLDOWN_MINUTES:-30}"
RULE="${ATP_ALERT_RULE:-streak_fail_3}"
TIME_WINDOW_MINS="${ATP_ALERT_TIME_WINDOW_MINUTES:-30}"
UPDATER_AGE_THRESHOLD="${ATP_ALERT_UPDATER_AGE_MINUTES:-5}"
STATE_FILE="/var/lib/atp/health_alert_state.json"
DRY_RUN="${ATP_ALERT_DRY_RUN:-0}"

load_telegram_env() {
  local f
  for f in "secrets/runtime.env" ".env" ".env.aws"; do
    if [ -f "$REPO_ROOT/$f" ]; then
      set +u
      # shellcheck source=/dev/null
      . "$REPO_ROOT/$f" 2>/dev/null || true
      set -u
    fi
  done
  [ -z "${TELEGRAM_CHAT_ID:-}" ] && [ -n "${TELEGRAM_CHAT_ID_AWS:-}" ] && TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID_AWS}"
  [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_BOT_TOKEN_AWS:-}" ] && TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN_AWS}"
}

main() {
  cd "$REPO_ROOT" || true
  load_telegram_env

  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
    echo "ATP health alert: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing; skip send."
    exit 0
  fi

  if [ ! -r "$LOG" ]; then
    echo "ATP health alert: log not readable: $LOG"
    exit 0
  fi

  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
  local now_ts now_epoch
  now_ts="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
  now_epoch="$(date -u +%s)"

  local streak=0 fail_count=0 updater_streak=0
  local last_ts="" last_verify="" last_md="" last_mu="" last_age="" last_global=""
  local lines
  lines="$(tail -n "$N" "$LOG" 2>/dev/null)" || true
  [ -z "$lines" ] && exit 0

  if command -v jq >/dev/null 2>&1; then
    # Consecutive FAIL streak from end of log
    streak="$(printf '%s' "$lines" | jq -s -r '
      (reverse | [.[].severity] | map(. == "FAIL") | (index(false) // length)) as $s | $s
    ' 2>/dev/null)" || streak=0
    streak="${streak:-0}"

    if [ "$RULE" = "fail_count_5_in_30m" ]; then
      local cut_epoch
      cut_epoch="$((now_epoch - TIME_WINDOW_MINS * 60))"
      fail_count="$(printf '%s' "$lines" | jq -s --argjson cut "$cut_epoch" '
        [ .[] | select(.severity == "FAIL" and .ts != null) |
          select((.ts | fromdate) >= $cut) ] | length
      ' 2>/dev/null)" || fail_count=0
    fi

    if [ "$RULE" = "updater_age_gt5_3runs" ]; then
      updater_streak="$(printf '%s' "$lines" | jq -s -r --argjson thresh "$UPDATER_AGE_THRESHOLD" '
        (reverse | [.[0:3][] | (.market_updater_age_minutes // 0 | if type == "number" then . else 0 end)] | map(select(. > $thresh)) | length) as $s | $s
      ' 2>/dev/null)" || updater_streak=0
    fi

    last_ts="$(printf '%s' "$lines" | tail -n 1 | jq -r '.ts // ""' 2>/dev/null)" || true
    last_verify="$(printf '%s' "$lines" | tail -n 1 | jq -r '.verify_label // ""' 2>/dev/null)" || true
    last_md="$(printf '%s' "$lines" | tail -n 1 | jq -r '.market_data_status // ""' 2>/dev/null)" || true
    last_mu="$(printf '%s' "$lines" | tail -n 1 | jq -r '.market_updater_status // ""' 2>/dev/null)" || true
    last_age="$(printf '%s' "$lines" | tail -n 1 | jq -r '.market_updater_age_minutes // ""' 2>/dev/null)" || true
    last_global="$(printf '%s' "$lines" | tail -n 1 | jq -r '.global_status // ""' 2>/dev/null)" || true
  else
    if [ "$RULE" != "streak_fail_3" ]; then
      exit 0
    fi
    # Consecutive FAIL at end (no jq): count from last line backwards
    streak="$(printf '%s' "$lines" | awk '
      { a[NR]=$0 }
      END {
        for (i=NR;i>=1;i--) if (a[i] ~ /"severity":"FAIL"/) c++; else break
        print c+0
      }
    ' 2>/dev/null)" || streak=0
    [ -z "$streak" ] && streak=0
  fi

  local triggered=0 reason=""
  case "$RULE" in
    streak_fail_3)        [ "${streak:-0}" -ge 3 ] 2>/dev/null && triggered=1 && reason="streak_fail_3 (streak=$streak)" ;;
    fail_count_5_in_30m) [ "${fail_count:-0}" -ge 5 ] 2>/dev/null && triggered=1 && reason="fail_count_5_in_30m (count=$fail_count)" ;;
    updater_age_gt5_3runs) [ "${updater_streak:-0}" -ge 3 ] 2>/dev/null && triggered=1 && reason="updater_age_gt5_3runs (runs=$updater_streak)" ;;
    *) exit 0 ;;
  esac

  [ "${triggered:-0}" -eq 0 ] && exit 0

  local last_sent_ts="" last_reason="" last_streak=0
  if [ -r "$STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
    last_sent_ts="$(jq -r '.last_sent_ts // ""' "$STATE_FILE" 2>/dev/null)" || true
    last_reason="$(jq -r '.last_reason // ""' "$STATE_FILE" 2>/dev/null)" || true
    last_streak="$(jq -r '.last_streak // 0' "$STATE_FILE" 2>/dev/null)" || true
  fi

  local send=1
  if [ -n "$last_sent_ts" ]; then
    local last_epoch diff_mins
    last_epoch="$(date -u -d "$last_sent_ts" +%s 2>/dev/null)" || last_epoch=0
    diff_mins="$(( (now_epoch - last_epoch) / 60 ))"
    if [ "${diff_mins:-999}" -lt "$COOLDOWN_MINS" ]; then
      send=0
      [ "$RULE" = "streak_fail_3" ] && [ "${streak:-0}" -gt "${last_streak:-0}" ] 2>/dev/null && send=1
      [[ "${last_reason:-}" != *"FAIL"* ]] && [[ "$reason" == *"FAIL"* ]] && send=1
    fi
  fi

  [ "${send:-0}" -eq 0 ] && exit 0

  local msg
  msg="🔄 ATP Health Alert ($now_ts)
Rule: $reason
FAIL streak: ${streak:-0}"
  [ "$RULE" = "fail_count_5_in_30m" ] && msg="$msg
FAIL count (${TIME_WINDOW_MINS}m): ${fail_count:-0}"
  msg="$msg

Last snapshot: ${last_ts:-n/a}
verify_label: ${last_verify:-n/a} | market_data: ${last_md:-n/a} | market_updater: ${last_mu:-n/a}
market_updater_age_min: ${last_age:-n/a} | global_status: ${last_global:-n/a}"

  if [ "$DRY_RUN" = "1" ]; then
    echo "ATP health alert (dry run): would send:"
    echo "$msg"
    echo "---"
    echo "curl -sS -X POST \"https://api.telegram.org/bot<TOKEN>/sendMessage\" -d \"chat_id=<REDACTED>\" --data-urlencode \"text=...\""
    exit 0
  fi

  curl -sS -X POST --max-time 10 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$msg" 2>/dev/null || true

  if command -v jq >/dev/null 2>&1; then
    jq -n --arg ts "$now_ts" --arg reason "$reason" --argjson streak "${streak:-0}" \
      '{last_sent_ts:$ts, last_reason:$reason, last_streak:$streak}' > "$STATE_FILE" 2>/dev/null || true
  else
    printf '{"last_sent_ts":"%s","last_reason":"%s","last_streak":%s}\n' "$now_ts" "$reason" "${streak:-0}" > "$STATE_FILE" 2>/dev/null || true
  fi

  exit 0
}

main "$@" || true
exit 0
