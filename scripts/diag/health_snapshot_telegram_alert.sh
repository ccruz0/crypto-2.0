#!/usr/bin/env bash
# Production-safe Telegram health alert: ACTION REQUIRED and RECOVERED only.
# Flow:
#   1) On FAIL streak: run targeted remediation silently (no Telegram). Log to /var/log/atp/health_alert_heal.log.
#   2) If remediation leads to PASS -> one "recovered" Telegram and clear incident.
#   3) Only when max remediation attempts reached and still FAIL -> send ONE "action required" Telegram per incident.
#   4) When system goes FAIL -> OK (e.g. after manual fix) -> one "recovered" Telegram.
# No alerts for: first failure, retries, ongoing streak, background healing. One alert per incident; no escalation resend.
# Runbook: docs/runbooks/ATP_HEALTH_ALERT_STREAK_FAIL.md
set -uo pipefail

REPO_ROOT="${ATP_REPO_ROOT:-$(cd "$(dirname "$0")/../.." && pwd)}"
LOG="${ATP_HEALTH_SNAPSHOT_LOG:-/var/log/atp/health_snapshots.log}"
N="${ATP_ALERT_LINES:-5000}"
COOLDOWN_MINS="${ATP_ALERT_COOLDOWN_MINUTES:-30}"
RULE="${ATP_ALERT_RULE:-streak_fail_3}"
TIME_WINDOW_MINS="${ATP_ALERT_TIME_WINDOW_MINUTES:-30}"
UPDATER_AGE_THRESHOLD="${ATP_ALERT_UPDATER_AGE_MINUTES:-5}"
STATE_FILE="${ATP_HEALTH_ALERT_STATE_FILE:-/var/lib/atp/health_alert_state.json}"
DRY_RUN="${ATP_ALERT_DRY_RUN:-0}"
BASE="${ATP_HEALTH_BASE:-http://127.0.0.1:8002}"
# Remediation / dedupe (align with backend/app/services/health_alert_incident.py)
REMEDIATION_ENABLED="${ATP_HEALTH_REMEDIATION_ENABLED:-1}"
REMEDIATION_GRACE_SEC="${ATP_HEALTH_REMEDIATION_GRACE_SECONDS:-300}"
MAX_REMEDIATION_ATTEMPTS="${ATP_HEALTH_REMEDIATION_MAX_ATTEMPTS:-3}"
# Severity: only send "action required" when severity == critical (e.g. market_data stale > N min)
CRITICAL_UPDATER_AGE_MINUTES="${ATP_HEALTH_CRITICAL_UPDATER_AGE_MINUTES:-30}"

load_telegram_env() {
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
  [ -z "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "${TELEGRAM_BOT_TOKEN_AWS:-}" ] && TELEGRAM_BOT_TOKEN="${TELEGRAM_BOT_TOKEN_AWS}"
  # Ops channel (AWS_alerts): health alerts use TELEGRAM_CHAT_ID_OPS when set; else TELEGRAM_CHAT_ID
  [ -z "${TELEGRAM_CHAT_ID_OPS:-}" ] && TELEGRAM_CHAT_ID_OPS="${TELEGRAM_CHAT_ID:-${TELEGRAM_CHAT_ID_AWS:-}}"
}

resolve_telegram_token() {
  if [ -n "${TELEGRAM_BOT_TOKEN:-}" ]; then
    return 0
  fi
  if [ -z "${TELEGRAM_BOT_TOKEN_ENCRYPTED:-}" ]; then
    return 1
  fi
  local tmpf
  tmpf="$(mktemp 2>/dev/null)" || true
  [ -z "$tmpf" ] || [ ! -w "$tmpf" ] && return 1
  local ret=1
  if (cd "$REPO_ROOT" && python3 "$REPO_ROOT/scripts/diag/decrypt_telegram_token_for_alert.py" "$tmpf" 2>/dev/null) && [ -r "$tmpf" ] && [ -s "$tmpf" ]; then
    TELEGRAM_BOT_TOKEN="$(cat "$tmpf")"
    ret=0
  fi
  rm -f "$tmpf" 2>/dev/null || true
  return "$ret"
}

send_tg() {
  local text="$1"
  if [ "$DRY_RUN" = "1" ]; then
    echo "ATP health alert (dry run): would send: $text"
    return 0
  fi
  local chat="${TELEGRAM_CHAT_ID_OPS:-$TELEGRAM_CHAT_ID}"
  [ -z "$chat" ] && return 1
  curl -sS -X POST --max-time 10 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${chat}" \
    --data-urlencode "text=$text" 2>/dev/null || true
}

# Send Telegram message with "Run full fix now" button (callback_data atp_run_full_fix).
# Backend handles the click and writes a trigger file; next health run will run full_fix_market_data.sh.
send_tg_with_button() {
  local text="$1"
  if [ "$DRY_RUN" = "1" ]; then
    echo "ATP health alert (dry run): would send with button: $text"
    return 0
  fi
  if ! command -v jq >/dev/null 2>&1; then
    send_tg "$text"
    return 0
  fi
  local chat="${TELEGRAM_CHAT_ID_OPS:-$TELEGRAM_CHAT_ID}"
  [ -z "$chat" ] && send_tg "$text" && return 0
  local payload
  payload="$(jq -n --arg chat_id "${chat}" --arg text "$text" \
    '{chat_id:$chat_id,text:$text,reply_markup:{inline_keyboard:[[{text:"▶ Run full fix now",callback_data:"atp_run_full_fix"}]]}}')"
  curl -sS -X POST --max-time 10 -H "Content-Type: application/json" \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "$payload" 2>/dev/null || true
}

log_heal() {
  echo "[$(date -u +"%Y-%m-%dT%H:%M:%SZ")] $*" >> /var/log/atp/health_alert_heal.log 2>/dev/null || true
}

is_market_incident() {
  local verify="$1" md="$2" mu="$3"
  case "$verify" in
    *MARKET_DATA*|*MARKET_UPDATER*) return 0 ;;
  esac
  [ "$md" = "FAIL" ] && [ "$mu" = "FAIL" ] && return 0
  return 1
}

# Classify incident severity: critical (alert) | warning | info (no Telegram for non-critical)
# critical: market_data stale > CRITICAL_UPDATER_AGE_MINUTES, or backend/API unreachable
# warning:  market_data stale but <= threshold, or other FAIL
# info:     minor / degraded
classify_severity() {
  local verify="$1" md="$2" mu="$3" age_min="$4"
  if is_market_incident "$verify" "$md" "$mu"; then
    # Numeric comparison: age > threshold -> critical
    if [ -n "$age_min" ] && [ "${age_min}" = "${age_min#*[!0-9.]*}" ] 2>/dev/null; then
      local age_int="${age_min%.*}"
      [ -z "$age_int" ] && age_int=0
      if [ "${age_int:-0}" -gt "${CRITICAL_UPDATER_AGE_MINUTES:-30}" ] 2>/dev/null; then
        echo "critical"
        return
      fi
      echo "warning"
      return
    fi
    echo "warning"
    return
  fi
  # Non-market: API/backend down is critical
  case "$verify" in
    *API_HEALTH*missing*|*API_HEALTH*timeout*|*connection*refused*) echo "critical" ;;
    *) echo "warning" ;;
  esac
}

state_get() {
  local key="$1"
  if [ -r "$STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
    jq -r ".[\"$key\"] // empty" "$STATE_FILE" 2>/dev/null || true
  else
    echo ""
  fi
}

state_write_full() {
  local json="$1"
  mkdir -p "$(dirname "$STATE_FILE")" 2>/dev/null || true
  printf '%s\n' "$json" > "$STATE_FILE" 2>/dev/null || true
}

# Merge new fields into existing state with jq
state_merge() {
  local now_ts="$1"
  if [ ! -r "$STATE_FILE" ] || ! command -v jq >/dev/null 2>&1; then
    jq -n --arg ts "$now_ts" \
      '{last_sent_ts:$ts,last_reason:"",last_streak:0,incident_open:true,incident_fingerprint:"",remediation_attempts:0,last_remediation_ts:"",last_escalation_ts:""}' > "$STATE_FILE" 2>/dev/null || true
    return
  fi
  jq --arg ts "$now_ts" "$2" "$STATE_FILE" > "${STATE_FILE}.tmp" 2>/dev/null && mv "${STATE_FILE}.tmp" "$STATE_FILE" 2>/dev/null || true
}

# If manual trigger was requested from Telegram button, run full fix once and clear trigger.
TRIGGER_FULL_FIX_FILE="${ATP_TRIGGER_FULL_FIX_FILE:-$REPO_ROOT/logs/trigger_full_fix}"
run_triggered_full_fix() {
  if [ -f "$TRIGGER_FULL_FIX_FILE" ]; then
    log_heal "event=manual_trigger_run trigger_file=$TRIGGER_FULL_FIX_FILE"
    rm -f "$TRIGGER_FULL_FIX_FILE"
    if [ -x "$REPO_ROOT/scripts/selfheal/full_fix_market_data.sh" ]; then
      ( cd "$REPO_ROOT" && REPO_DIR="$REPO_ROOT" ATP_HEALTH_BASE="${BASE}" nohup ./scripts/selfheal/full_fix_market_data.sh >> /var/log/atp/health_alert_heal.log 2>&1 ) &
    fi
    return 0
  fi
  return 1
}

main() {
  cd "$REPO_ROOT" || true
  load_telegram_env

  # Manual "Run full fix now" from Telegram: run once and continue with normal health check
  run_triggered_full_fix || true

  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    resolve_telegram_token || true
  fi
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || { [ -z "${TELEGRAM_CHAT_ID_OPS:-}" ] && [ -z "${TELEGRAM_CHAT_ID:-}" ]; }; then
    if [ -n "${TELEGRAM_BOT_TOKEN_ENCRYPTED:-}" ]; then
      enc_len="${#TELEGRAM_BOT_TOKEN_ENCRYPTED}"
      if [ "$enc_len" -lt 80 ] 2>/dev/null; then
        echo "ATP health alert: TELEGRAM_BOT_TOKEN_ENCRYPTED looks truncated (length $enc_len < 80)."
      fi
      echo "ATP health alert: decryption failed; skip send."
    else
      echo "ATP health alert: TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID missing; skip send."
    fi
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
  local last_ts="" last_verify="" last_md="" last_mu="" last_age="" last_global="" last_severity=""
  local lines
  lines="$(tail -n "$N" "$LOG" 2>/dev/null)" || true
  [ -z "$lines" ] && exit 0

  if command -v jq >/dev/null 2>&1; then
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
    last_severity="$(printf '%s' "$lines" | tail -n 1 | jq -r '.severity // ""' 2>/dev/null)" || true
  else
    if [ "$RULE" != "streak_fail_3" ]; then
      exit 0
    fi
    streak="$(printf '%s' "$lines" | awk '
      { a[NR]=$0 }
      END {
        for (i=NR;i>=1;i--) if (a[i] ~ /"severity":"FAIL"/) c++; else break
        print c+0
      }
    ' 2>/dev/null)" || streak=0
    [ -z "$streak" ] && streak=0
  fi

  # --- Recovery path: last snapshot OK and we had an open incident -> one recovered message ---
  if [ "$last_severity" = "OK" ] && command -v jq >/dev/null 2>&1 && [ -r "$STATE_FILE" ]; then
    local was_open
    was_open="$(jq -r '.incident_open // false' "$STATE_FILE" 2>/dev/null)"
    if [ "$was_open" = "true" ]; then
      log_heal "event=incident_resolved verify_label=${last_verify:-n/a}"
      send_tg "✅ ATP Health recovered ($now_ts)
Previous incident cleared. Last snapshot OK.
(If you applied a manual fix, this confirms it took effect.)
verify_label: ${last_verify:-n/a} | market_data: ${last_md:-n/a} | market_updater: ${last_mu:-n/a}"
      jq -n --arg ts "$now_ts" \
        '{last_sent_ts:$ts,last_reason:"resolved",last_streak:0,incident_open:false,incident_fingerprint:"",remediation_attempts:0,last_remediation_ts:"",last_escalation_ts:"",first_fail_ts:"",action_alert_sent:false}' > "$STATE_FILE" 2>/dev/null || true
      exit 0
    fi
  fi

  local triggered=0 reason=""
  case "$RULE" in
    streak_fail_3)        [ "${streak:-0}" -ge 3 ] 2>/dev/null && triggered=1 && reason="streak_fail_3 (streak=$streak)" ;;
    fail_count_5_in_30m) [ "${fail_count:-0}" -ge 5 ] 2>/dev/null && triggered=1 && reason="fail_count_5_in_30m (count=$fail_count)" ;;
    updater_age_gt5_3runs) [ "${updater_streak:-0}" -ge 3 ] 2>/dev/null && triggered=1 && reason="updater_age_gt5_3runs (runs=$updater_streak)" ;;
    *) exit 0 ;;
  esac

  [ "${triggered:-0}" -eq 0 ] && exit 0

  # --- Incident fingerprint and state (one alert per incident) ---
  local fp="${last_verify}|${last_md}|${last_mu}"
  local stored_fp="" attempts=0 action_alert_sent="" first_fail_ts=""
  stored_fp="$(state_get incident_fingerprint)"
  attempts="$(state_get remediation_attempts)"
  [ -z "$attempts" ] && attempts=0
  action_alert_sent="$(state_get action_alert_sent)"
  first_fail_ts="$(state_get first_fail_ts)"

  # New incident: reset attempts and alert-sent flag
  if [ "$stored_fp" != "$fp" ]; then
    attempts=0
    action_alert_sent=""
    first_fail_ts="$now_ts"
  fi

  # --- MARKET_DATA incident: run remediation silently (no Telegram) ---
  if [ "$REMEDIATION_ENABLED" = "1" ] && is_market_incident "$last_verify" "$last_md" "$last_mu"; then
    if [ "${attempts:-0}" -lt "$MAX_REMEDIATION_ATTEMPTS" ] && [ -x "$REPO_ROOT/scripts/selfheal/remediate_market_data.sh" ]; then
      log_heal "event=remediation_started attempt=$((attempts + 1)) max=$MAX_REMEDIATION_ATTEMPTS verify_label=${last_verify:-n/a} (no TG)"
      REPO_DIR="$REPO_ROOT" ATP_HEALTH_BASE="$BASE" ATP_REMEDIATE_DRY_RUN="$DRY_RUN" \
        bash "$REPO_ROOT/scripts/selfheal/remediate_market_data.sh" 2>/dev/null | while read -r line; do log_heal "$line"; done || true
      if [ "$DRY_RUN" != "1" ] && [ "$REMEDIATION_GRACE_SEC" -gt 0 ] 2>/dev/null; then
        sleep "$REMEDIATION_GRACE_SEC"
      fi
      if [ "$DRY_RUN" != "1" ] && [ -x "$REPO_ROOT/scripts/selfheal/verify.sh" ]; then
        if REPO_DIR="$REPO_ROOT" BASE="$BASE" "$REPO_ROOT/scripts/selfheal/verify.sh" >/dev/null 2>&1; then
          log_heal "event=post_remediation_verification result=PASS"
          send_tg "✅ ATP Health recovered ($now_ts)
Remediation succeeded after restart/update-cache.
verify_label: PASS (was ${last_verify:-n/a})"
          jq -n --arg ts "$now_ts" \
            '{last_sent_ts:$ts,last_reason:"recovered_after_remediation",last_streak:0,incident_open:false,incident_fingerprint:"",remediation_attempts:0,last_remediation_ts:"",last_escalation_ts:"",first_fail_ts:"",action_alert_sent:false}' > "$STATE_FILE" 2>/dev/null || true
          exit 0
        fi
        log_heal "event=post_remediation_verification result=FAIL"
      fi
      attempts=$((attempts + 1))
      # Persist: incident open, first_fail_ts (use existing or now for new incident)
      if command -v jq >/dev/null 2>&1; then
        prev="{}"
        [ -r "$STATE_FILE" ] && prev="$(cat "$STATE_FILE" 2>/dev/null || echo '{}')"
        echo "$prev" | jq \
          --arg ts "$now_ts" \
          --arg fp "$fp" \
          --arg fft "${first_fail_ts:-$now_ts}" \
          --argjson att "$attempts" \
          --argjson streak "$streak" \
          --arg reason "$reason" \
          '. + {last_remediation_ts:$ts,incident_open:true,incident_fingerprint:$fp,first_fail_ts:$fft,remediation_attempts:$att,last_streak:$streak,last_reason:$reason}' \
          2>/dev/null > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE" 2>/dev/null || true
      fi
      exit 0
    fi
  fi

  # --- Do not resend: one alert per incident (action_alert_sent) ---
  if [ "$action_alert_sent" = "true" ]; then
    log_heal "event=action_alert_already_sent fingerprint=$fp (no resend)"
    if [ "$DRY_RUN" != "1" ] && [ "${attempts:-0}" -ge "$MAX_REMEDIATION_ATTEMPTS" ] && is_market_incident "$last_verify" "$last_md" "$last_mu" && [ -x "$REPO_ROOT/scripts/selfheal/full_fix_market_data.sh" ]; then
      ( cd "$REPO_ROOT" && REPO_DIR="$REPO_ROOT" ATP_HEALTH_BASE="${BASE}" nohup ./scripts/selfheal/full_fix_market_data.sh >> /var/log/atp/health_alert_heal.log 2>&1 ) &
    fi
    exit 0
  fi

  # Send only when: remediation_failed (market and max attempts reached, or non-market) AND severity == critical
  local should_send=0
  if is_market_incident "$last_verify" "$last_md" "$last_mu"; then
    [ "${attempts:-0}" -ge "$MAX_REMEDIATION_ATTEMPTS" ] && should_send=1
  else
    should_send=1
  fi
  [ "$should_send" -eq 0 ] && exit 0

  # --- Severity: only send "action required" for critical ---
  local incident_severity
  incident_severity="$(classify_severity "$last_verify" "$last_md" "$last_mu" "$last_age")"
  if [ "$incident_severity" != "critical" ]; then
    log_heal "event=action_required_skipped severity=$incident_severity (only critical triggers Telegram) reason=$reason attempts=${attempts:-0}"
    exit 0
  fi

  # --- Time since failure (minutes) ---
  local mins_since_fail=""
  if [ -n "$first_fail_ts" ]; then
    local first_epoch
    first_epoch="$(date -u -d "$first_fail_ts" +%s 2>/dev/null)" || first_epoch=0
    mins_since_fail="$(( (now_epoch - first_epoch) / 60 ))"
  fi
  [ -z "$mins_since_fail" ] && mins_since_fail="n/a"

  # --- Root cause and single "action required" message (include severity) ---
  local root_cause=""
  if is_market_incident "$last_verify" "$last_md" "$last_mu"; then
    root_cause="Market data stale (market_updater not updating). market_updater_age_min: ${last_age:-n/a} | verify_label: ${last_verify:-n/a}"
  else
    root_cause="Health check failing. verify_label: ${last_verify:-n/a} | market_data: ${last_md:-n/a} | market_updater: ${last_mu:-n/a}"
  fi

  local msg
  msg="🚨 ATP Health — action required ($now_ts)
Severity: $incident_severity

Root cause: $root_cause
Failing since: ${mins_since_fail} min ago
Last snapshot: ${last_ts:-n/a} | global_status: ${last_global:-n/a}"

  if is_market_incident "$last_verify" "$last_md" "$last_mu"; then
    msg="$msg

Action: Runbook EC2_FIX_MARKET_DATA_NOW — SSH to prod, restart stack + market-updater, POST /api/market/update-cache. Or tap the button below to trigger full fix on next health check.
Log: /var/log/atp/health_alert_heal.log"
    send_tg_with_button "$msg"
  else
    msg="$msg

Action: Check backend and runbook ATP_HEALTH_ALERT_STREAK_FAIL.md. Log: /var/log/atp/health_alert_heal.log"
    send_tg "$msg"
  fi

  if command -v jq >/dev/null 2>&1; then
    health_alert_payload="$(jq -n \
      --arg rule "${RULE}" \
      --arg reason "${reason}" \
      --arg severity "${incident_severity}" \
      --argjson streak "${streak:-0}" \
      --arg ts "${last_ts:-n/a}" \
      --arg verify "${last_verify:-n/a}" \
      --arg md "${last_md:-n/a}" \
      --arg mu "${last_mu:-n/a}" \
      --arg age "${last_age:-n/a}" \
      --arg global "${last_global:-n/a}" \
      '{rule:$rule, reason:$reason, severity:$severity, streak:$streak, last_ts:$ts, verify_label:$verify, market_data_status:$md, market_updater_status:$mu, market_updater_age_min:$age, global_status:$global}')"
    curl -sS -X POST --max-time 15 -H "Content-Type: application/json" \
      -d "$health_alert_payload" "$BASE/api/monitoring/health-alert" 2>/dev/null || true
  fi

  # Persist: mark action_alert_sent so we never resend for this incident
  if command -v jq >/dev/null 2>&1; then
    jq -n \
      --arg ts "$now_ts" \
      --arg reason "$reason" \
      --argjson streak "${streak:-0}" \
      --arg fp "$fp" \
      --argjson att "${attempts:-0}" \
      --arg fft "${first_fail_ts:-$now_ts}" \
      '{
        last_sent_ts:$ts,
        last_reason:$reason,
        last_streak:$streak,
        incident_open:true,
        incident_fingerprint:$fp,
        remediation_attempts:$att,
        last_escalation_ts:$ts,
        first_fail_ts:$fft,
        action_alert_sent:true
      }' > "$STATE_FILE" 2>/dev/null || true
  fi

  log_heal "event=action_required_alert_sent reason=$reason attempts=${attempts:-0} fingerprint=$fp"

  # Run full fix in background (no separate Telegram)
  if [ "$DRY_RUN" != "1" ] && [ "${attempts:-0}" -ge "$MAX_REMEDIATION_ATTEMPTS" ]; then
    if is_market_incident "$last_verify" "$last_md" "$last_mu" && [ -x "$REPO_ROOT/scripts/selfheal/full_fix_market_data.sh" ]; then
      ( cd "$REPO_ROOT" && REPO_DIR="$REPO_ROOT" ATP_HEALTH_BASE="${BASE}" nohup ./scripts/selfheal/full_fix_market_data.sh >> /var/log/atp/health_alert_heal.log 2>&1 ) &
    elif [ -x "$REPO_ROOT/scripts/selfheal/heal.sh" ]; then
      ( cd "$REPO_ROOT" && nohup ./scripts/selfheal/heal.sh >> /var/log/atp/health_alert_heal.log 2>&1 ) &
    fi
  fi

  exit 0
}

main "$@" || true
exit 0
