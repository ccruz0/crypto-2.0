#!/usr/bin/env bash
# Production-safe Telegram alert for health snapshot failures.
# Flow (MARKET_DATA / market_updater):
#   1) On FAIL streak: run targeted remediation first (restart market-updater-aws, then POST update-cache; health/fix not before cache).
#   2) Grace wait + re-verify; if PASS -> one Telegram "resolved" and clear incident.
#   3) If still FAIL -> one escalation Telegram + incident state; repeated cycles deduped (no spam).
# Reads last N lines from health_snapshots.log; uses STATE_FILE for cooldown + incident dedupe.
# Exit 0 always. No hardcoded secrets; token/chat_id from env files.
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
ESCALATION_COOLDOWN_MINS="${ATP_HEALTH_ESCALATION_COOLDOWN_MINUTES:-120}"
# Telegram updates about remediation (start/finish). Set 0 to disable extra TG during remediation.
REMEDIATION_TG="${ATP_HEALTH_REMEDIATION_TELEGRAM:-1}"

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
  curl -sS -X POST --max-time 10 \
    "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_CHAT_ID}" \
    --data-urlencode "text=$text" 2>/dev/null || true
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

main() {
  cd "$REPO_ROOT" || true
  load_telegram_env

  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then
    resolve_telegram_token || true
  fi
  if [ -z "${TELEGRAM_BOT_TOKEN:-}" ] || [ -z "${TELEGRAM_CHAT_ID:-}" ]; then
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

  # --- Recovery path: last snapshot OK and we had an open incident -> one resolved message ---
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
        '{last_sent_ts:$ts,last_reason:"resolved",last_streak:0,incident_open:false,incident_fingerprint:"",remediation_attempts:0,last_remediation_ts:"",last_escalation_ts:""}' > "$STATE_FILE" 2>/dev/null || true
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

  # --- MARKET_DATA incident: remediate before alerting ---
  local attempts=0
  if [ "$REMEDIATION_ENABLED" = "1" ] && is_market_incident "$last_verify" "$last_md" "$last_mu"; then
    attempts="$(state_get remediation_attempts)"
    [ -z "$attempts" ] && attempts=0
    # Cap attempts per incident fingerprint
    local fp="${last_verify}|${last_md}|${last_mu}"
    local stored_fp
    stored_fp="$(state_get incident_fingerprint)"
    if [ "$stored_fp" != "$fp" ]; then
      attempts=0
    fi
    if [ "${attempts:-0}" -lt "$MAX_REMEDIATION_ATTEMPTS" ] && [ -x "$REPO_ROOT/scripts/selfheal/remediate_market_data.sh" ]; then
      log_heal "event=remediation_started attempt=$((attempts + 1)) max=$MAX_REMEDIATION_ATTEMPTS verify_label=${last_verify:-n/a}"
      if [ "$REMEDIATION_TG" = "1" ]; then
        send_tg "🔧 ATP remediation starting ($now_ts)
Attempt $((attempts + 1))/${MAX_REMEDIATION_ATTEMPTS} for market_data/market_updater failure.

Actions: restart market-updater-aws → POST /api/market/update-cache (timeout 300s, retry on empty reply). health/fix is NOT called before cache (avoids empty reply). Optional after: ATP_REMEDIATE_RUN_HEALTH_FIX=1
Then ${REMEDIATION_GRACE_SEC}s grace + re-verify.

verify_label: ${last_verify:-n/a} | market_updater_age_min: ${last_age:-n/a}
Log: /var/log/atp/health_alert_heal.log"
      fi
      REPO_DIR="$REPO_ROOT" ATP_HEALTH_BASE="$BASE" ATP_REMEDIATE_DRY_RUN="$DRY_RUN" \
        bash "$REPO_ROOT/scripts/selfheal/remediate_market_data.sh" 2>/dev/null | while read -r line; do log_heal "$line"; done || true
      # Grace then re-verify
      if [ "$DRY_RUN" != "1" ] && [ "$REMEDIATION_GRACE_SEC" -gt 0 ] 2>/dev/null; then
        sleep "$REMEDIATION_GRACE_SEC"
      fi
      if [ "$DRY_RUN" != "1" ] && [ -x "$REPO_ROOT/scripts/selfheal/verify.sh" ]; then
        if REPO_DIR="$REPO_ROOT" BASE="$BASE" "$REPO_ROOT/scripts/selfheal/verify.sh" >/dev/null 2>&1; then
          log_heal "event=post_remediation_verification result=PASS"
          send_tg "✅ ATP Health recovered ($now_ts)
Remediation succeeded after restart/update-cache.
(No manual step needed unless you changed something else.)
verify_label: PASS (was ${last_verify:-n/a})"
          jq -n --arg ts "$now_ts" \
            '{last_sent_ts:$ts,last_reason:"recovered_after_remediation",last_streak:0,incident_open:false,incident_fingerprint:"",remediation_attempts:0,last_remediation_ts:"",last_escalation_ts:""}' > "$STATE_FILE" 2>/dev/null || true
          exit 0
        fi
        log_heal "event=post_remediation_verification result=FAIL"
        if [ "$REMEDIATION_TG" = "1" ]; then
          # Template v2: no health/fix before update-cache (see remediate_market_data.sh).
          _remedy_line="Attempt $((attempts + 1))/$MAX_REMEDIATION_ATTEMPTS ran: restart market-updater-aws → POST /api/market/update-cache only (300s timeout + retry). Then ${REMEDIATION_GRACE_SEC}s grace + verify."
          if [ "$((attempts + 1))" -ge "$MAX_REMEDIATION_ATTEMPTS" ]; then
            _next_line="Max attempts reached — escalation Telegram + background heal.sh (full stack) run next per runbook."
          else
            _next_line="Next timer run will try again ($((${attempts} + 2))/$MAX_REMEDIATION_ATTEMPTS)."
          fi
          send_tg "⚠️ ATP remediation finished — still FAIL ($now_ts)
$_remedy_line
$_next_line

Manual fix: next OK snapshot sends ✅ recovered.
verify_label still: ${last_verify:-n/a}
Runbook: ATP_HEALTH_ALERT_STREAK_FAIL.md | Log: /var/log/atp/health_alert_heal.log"
        fi
      fi
      attempts=$((attempts + 1))
      # Persist remediation attempt + grace anchor
      if command -v jq >/dev/null 2>&1; then
        prev="{}"
        [ -r "$STATE_FILE" ] && prev="$(cat "$STATE_FILE" 2>/dev/null || echo '{}')"
        echo "$prev" | jq \
          --arg ts "$now_ts" \
          --arg fp "$fp" \
          --argjson att "$attempts" \
          --argjson streak "$streak" \
          --arg reason "$reason" \
          '. + {last_remediation_ts:$ts,incident_open:true,incident_fingerprint:$fp,remediation_attempts:$att,last_streak:$streak,last_reason:$reason}' \
          2>/dev/null > "${STATE_FILE}.tmp" && mv "${STATE_FILE}.tmp" "$STATE_FILE" 2>/dev/null || true
      fi
    fi
  fi

  # --- Dedupe: do not resend on streak growth alone (cooldown for same incident) ---
  local send=1
  local last_sent_ts="" last_reason="" last_streak=0 incident_open=""
  if [ -r "$STATE_FILE" ] && command -v jq >/dev/null 2>&1; then
    last_sent_ts="$(jq -r '.last_sent_ts // ""' "$STATE_FILE" 2>/dev/null)" || true
    last_reason="$(jq -r '.last_reason // ""' "$STATE_FILE" 2>/dev/null)" || true
    last_streak="$(jq -r '.last_streak // 0' "$STATE_FILE" 2>/dev/null)" || true
    incident_open="$(jq -r '.incident_open // false' "$STATE_FILE" 2>/dev/null)" || true
  fi

  if [ -n "$last_sent_ts" ]; then
    local last_epoch diff_mins
    last_epoch="$(date -u -d "$last_sent_ts" +%s 2>/dev/null)" || last_epoch=0
    diff_mins="$(( (now_epoch - last_epoch) / 60 ))"
    if [ "${diff_mins:-999}" -lt "$COOLDOWN_MINS" ]; then
      send=0
      # Removed: streak bypass that caused spam when streak 3->4->5
      # Escalation only after escalation cooldown if incident still open and market incident
      if [ "$incident_open" = "true" ] && is_market_incident "$last_verify" "$last_md" "$last_mu"; then
        local last_esc
        last_esc="$(state_get last_escalation_ts)"
        if [ -n "$last_esc" ]; then
          local esc_epoch esc_diff
          esc_epoch="$(date -u -d "$last_esc" +%s 2>/dev/null)" || esc_epoch=0
          esc_diff="$(( (now_epoch - esc_epoch) / 60 ))"
          if [ "${esc_diff:-0}" -ge "$ESCALATION_COOLDOWN_MINS" ] && [ "${attempts:-0}" -ge "$MAX_REMEDIATION_ATTEMPTS" ]; then
            send=1
            log_heal "event=escalation_alert_send reason=escalation_cooldown_elapsed attempts=$attempts"
          fi
        fi
      fi
    fi
  fi

  [ "${send:-0}" -eq 0 ] && exit 0

  local msg
  msg="🔄 ATP Health Alert ($now_ts)
Rule: $reason
FAIL streak: ${streak:-0}"
  [ "$RULE" = "fail_count_5_in_30m" ] && msg="$msg
FAIL count (${TIME_WINDOW_MINS}m): ${fail_count:-0}"
  if [ "${attempts:-0}" -gt 0 ]; then
    msg="$msg
Remediation attempts so far: ${attempts}/${MAX_REMEDIATION_ATTEMPTS}
You should have received TG for each remediation start/finish; see /var/log/atp/health_alert_heal.log"
  fi
  msg="$msg

Last snapshot: ${last_ts:-n/a}
verify_label: ${last_verify:-n/a} | market_data: ${last_md:-n/a} | market_updater: ${last_mu:-n/a}
market_updater_age_min: ${last_age:-n/a} | global_status: ${last_global:-n/a}"

  send_tg "$msg"

  if command -v jq >/dev/null 2>&1; then
    health_alert_payload="$(jq -n \
      --arg rule "${RULE}" \
      --arg reason "${reason}" \
      --argjson streak "${streak:-0}" \
      --arg ts "${last_ts:-n/a}" \
      --arg verify "${last_verify:-n/a}" \
      --arg md "${last_md:-n/a}" \
      --arg mu "${last_mu:-n/a}" \
      --arg age "${last_age:-n/a}" \
      --arg global "${last_global:-n/a}" \
      '{rule:$rule, reason:$reason, streak:$streak, last_ts:$ts, verify_label:$verify, market_data_status:$md, market_updater_status:$mu, market_updater_age_min:$age, global_status:$global}')"
    curl -sS -X POST --max-time 15 -H "Content-Type: application/json" \
      -d "$health_alert_payload" "$BASE/api/monitoring/health-alert" 2>/dev/null || true
  fi

  # Persist state: incident open, escalation timestamp for cooldown
  if command -v jq >/dev/null 2>&1; then
    local fp2="${last_verify}|${last_md}|${last_mu}"
    jq -n \
      --arg ts "$now_ts" \
      --arg reason "$reason" \
      --argjson streak "${streak:-0}" \
      --arg fp "$fp2" \
      --argjson att "${attempts:-0}" \
      '{
        last_sent_ts:$ts,
        last_reason:$reason,
        last_streak:$streak,
        incident_open:true,
        incident_fingerprint:$fp,
        remediation_attempts:$att,
        last_escalation_ts:$ts
      }' > "$STATE_FILE" 2>/dev/null || true
  else
    printf '{"last_sent_ts":"%s","last_reason":"%s","last_streak":%s}\n' "$now_ts" "$reason" "${streak:-0}" > "$STATE_FILE" 2>/dev/null || true
  fi

  log_heal "event=escalation_alert_sent reason=$reason attempts=${attempts:-0}"

  # Optional: background full heal only if remediation script not enough (heavy)
  if [ "$DRY_RUN" != "1" ] && [ -x "$REPO_ROOT/scripts/selfheal/heal.sh" ] && [ "${attempts:-0}" -ge "$MAX_REMEDIATION_ATTEMPTS" ]; then
    if [ "$REMEDIATION_TG" = "1" ]; then
      send_tg "🔁 ATP full self-heal starting in background ($now_ts)
Targeted remediation reached max attempts ($MAX_REMEDIATION_ATTEMPTS). Running heal.sh (stack restart / disk cleanup as needed).

You will get ✅ recovered when health returns OK. Log: /var/log/atp/health_alert_heal.log"
    fi
    ( cd "$REPO_ROOT" && nohup ./scripts/selfheal/heal.sh >> /var/log/atp/health_alert_heal.log 2>&1 ) &
  fi

  exit 0
}

main "$@" || true
exit 0
