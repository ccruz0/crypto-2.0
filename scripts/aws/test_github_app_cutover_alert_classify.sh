#!/usr/bin/env bash
# Unit tests for cutover alert classification (no docker / no network).
# Usage: bash scripts/aws/test_github_app_cutover_alert_classify.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/aws/_github_app_cutover_alert_lib.sh
source "$SCRIPT_DIR/_github_app_cutover_alert_lib.sh"

PASS=0
FAIL=0

assert_eq() {
  local name="$1" expected="$2" actual="$3"
  if [[ "$expected" == "$actual" ]]; then
    echo "PASS: $name"
    PASS=$((PASS + 1))
  else
    echo "FAIL: $name (expected=$expected actual=$actual)"
    FAIL=$((FAIL + 1))
  fi
}

SAMPLE_TRANSIENT=$(cat <<'EOF'
== Summary ==
Failures:
  - backend-aws health starting
  - backend-aws-canary health starting
  - backend-aws /ping_fast not ok
  - backend-aws /api/health/ready not ready
  - backend-aws-canary /ping_fast not ok
  - backend-aws-canary /api/health/ready not ready
  - backend-aws-canary logs contain GitHub auth warnings
EXCHANGE_CREDENTIAL_WARNINGS=NO
GITHUB_APP_CUTOVER_HEALTH=FAIL
EOF
)

fails="$(extract_monitor_failures "$SAMPLE_TRANSIENT")"
count="$(echo "$fails" | grep -c . || true)"
assert_eq "extract_count_transient_sample" "7" "$count"

sev="$(classify_failure "github_app" "YES" "yes" "$fails")"
assert_eq "classify_1500_style_transient" "TRANSIENT" "$sev"

sev="$(classify_failure "legacy_pat" "YES" "yes" "$fails")"
assert_eq "classify_wrong_auth_mode" "AUTH" "$sev"

sev="$(classify_failure "github_app" "NO" "yes" "$fails")"
assert_eq "classify_cutover_not_ready" "AUTH" "$sev"

sev="$(classify_failure "github_app" "YES" "no" "$fails")"
assert_eq "classify_mint_failed" "AUTH" "$sev"

other_fails=$'backend-aws something unexpected\nbackend-aws health starting'
sev="$(classify_failure "github_app" "YES" "yes" "$other_fails")"
assert_eq "classify_mixed_other" "OTHER" "$sev"

diag_line='backend-aws-1 | GitHub auth diagnostics: {legacy_pat_escape_hatch: False}'
# Monitor pattern must not treat diagnostic key as auth_method=legacy_pat
if echo "$diag_line" | grep -Eiq 'auth_method=legacy_pat'; then
  assert_eq "diag_line_not_auth_method_legacy_pat" "no_match" "matched"
else
  assert_eq "diag_line_not_auth_method_legacy_pat" "no_match" "no_match"
fi

# Broad legacy_pat would false-positive; ensure we require auth_method= prefix
if echo "$diag_line" | grep -Eiq 'auth_method=legacy_pat|failed to mint|GitHub API auth unavailable|auth_method=none|PermissionError'; then
  assert_eq "new_patterns_skip_diagnostics" "no_match" "matched"
else
  assert_eq "new_patterns_skip_diagnostics" "no_match" "no_match"
fi

# --- 2026-08-12 ATP Control false AUTH (backend down → auth_mode unknown) ---
SAMPLE_DOWN=$(cat <<'EOF'
== Summary ==
Failures:
  - backend-aws unhealthy
  - backend-aws-canary unhealthy
  - backend-aws /api/health/ready not ready
  - backend-aws-canary /api/health/ready not ready
  - auth_mode is not github_app (got unknown)
  - CUTOVER_READY is not YES (got NO)
  - live token mint not confirmed
EXCHANGE_CREDENTIAL_WARNINGS=NO
GITHUB_APP_CUTOVER_HEALTH=FAIL
EOF
)
down_fails="$(extract_monitor_failures "$SAMPLE_DOWN")"
sev="$(classify_failure "unknown" "NO" "no" "$down_fails")"
assert_eq "classify_backend_down_unknown_as_transient" "TRANSIENT" "$sev"

# Empty failure list + unknown auth → TRANSIENT (infra; monitor parse incomplete)
sev="$(classify_failure "unknown" "NO" "no" "")"
assert_eq "classify_unknown_empty_failures_transient" "TRANSIENT" "$sev"

# Real AUTH: auth_mode none with healthy-looking cutover flags still AUTH
sev="$(classify_failure "none" "NO" "no" $'auth_mode is not github_app (got none)\nCUTOVER_READY is not YES (got NO)')"
assert_eq "classify_auth_mode_none_is_auth" "AUTH" "$sev"

# Real AUTH: github_app env present but mint failed while auth_mode known
sev="$(classify_failure "github_app" "NO" "no" $'CUTOVER_READY is not YES (got NO)\nlive token mint not confirmed')"
assert_eq "classify_mint_fail_with_known_mode_auth" "AUTH" "$sev"

# Auto-heal disabled path
tmp_log="$(mktemp -d)"
out="$(GITHUB_APP_CUTOVER_AUTO_HEAL=0 attempt_cutover_infra_auto_heal "$SCRIPT_DIR/../.." "$tmp_log" "$tmp_log/cooldown" 2>&1)" || true
echo "$out" | grep -q "auto-heal skipped: GITHUB_APP_CUTOVER_AUTO_HEAL=0" \
  && assert_eq "auto_heal_disabled" "skipped" "skipped" \
  || assert_eq "auto_heal_disabled" "skipped" "not_skipped"
rm -rf "$tmp_log"

# Deploy marker blocks auto-heal
tmp_log="$(mktemp -d)"
marker="$(mktemp)"
echo "epoch=$(date +%s)" >"$marker"
out="$(ATP_DEPLOY_MARKER="$marker" GITHUB_APP_CUTOVER_AUTO_HEAL=1 \
  attempt_cutover_infra_auto_heal "$SCRIPT_DIR/../.." "$tmp_log" "$tmp_log/cooldown" 2>&1)" || true
echo "$out" | grep -q "deploy in progress" \
  && assert_eq "auto_heal_blocked_by_deploy_marker" "blocked" "blocked" \
  || assert_eq "auto_heal_blocked_by_deploy_marker" "blocked" "not_blocked"
rm -f "$marker"
rm -rf "$tmp_log"

# Disk reclaim helper: threshold high so reclaim is skipped on normal CI disks
out="$(GITHUB_APP_CUTOVER_DISK_RECLAIM_PCT=101 reclaim_disk_for_cutover_heal "$SCRIPT_DIR/../.." 2>&1)" || true
echo "$out" | grep -q "reclaim if >=" \
  && assert_eq "disk_reclaim_skips_when_under_threshold" "ok" "ok" \
  || assert_eq "disk_reclaim_skips_when_under_threshold" "ok" "missing"
# Force reclaim path (threshold 0) but do not require docker success
out="$(GITHUB_APP_CUTOVER_DISK_RECLAIM_PCT=0 reclaim_disk_for_cutover_heal "$SCRIPT_DIR/../.." 2>&1)" || true
echo "$out" | grep -q "disk critically full" \
  && assert_eq "disk_reclaim_runs_when_over_threshold" "ok" "ok" \
  || assert_eq "disk_reclaim_runs_when_over_threshold" "ok" "missing"

# ENOSPC retry must use prod_compose (PROD runtime.env mode 600), not bare compose.
# Source-check both call sites of _restart_backend_aws_for_cutover_heal + helper body.
helper_def="$(sed -n '/^_restart_backend_aws_for_cutover_heal()/,/^}/p' "$SCRIPT_DIR/_github_app_cutover_alert_lib.sh")"
echo "$helper_def" | grep -q 'prod_compose.sh restart backend-aws' \
  && assert_eq "restart_helper_uses_prod_compose" "ok" "ok" \
  || assert_eq "restart_helper_uses_prod_compose" "ok" "missing"
# Ensure ENOSPC path reuses the helper (not a bare docker compose restart).
enospc_block="$(awk '/restart hit ENOSPC/,/ping_fast OK after backend-aws restart|still unhealthy after recovery/ {print}' \
  "$SCRIPT_DIR/_github_app_cutover_alert_lib.sh")"
echo "$enospc_block" | grep -q '_restart_backend_aws_for_cutover_heal' \
  && assert_eq "enospc_retry_uses_restart_helper" "ok" "ok" \
  || assert_eq "enospc_retry_uses_restart_helper" "ok" "missing"
if echo "$enospc_block" | grep -E 'docker compose --profile aws restart backend-aws' | grep -vq '_restart'; then
  assert_eq "enospc_retry_no_bare_compose" "ok" "bare_compose_present"
else
  assert_eq "enospc_retry_no_bare_compose" "ok" "ok"
fi

# Runner: recovery Telegram only when note is exact healed string (not skipped*).
runner="$SCRIPT_DIR/run_github_app_cutover_monitor_with_alerts.sh"
grep -q 'AUTO_HEAL_NOTE="attempted — ping_fast recovered"' "$runner" \
  && grep -q 'AUTO_HEAL_NOTE" == "attempted — ping_fast recovered"' "$runner" \
  && grep -q 'auto-heal skipped:' "$runner" \
  && assert_eq "recovery_notify_requires_real_heal" "ok" "ok" \
  || assert_eq "recovery_notify_requires_real_heal" "ok" "missing"

echo
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
