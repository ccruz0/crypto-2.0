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

echo
echo "Results: PASS=$PASS FAIL=$FAIL"
[[ "$FAIL" -eq 0 ]]
