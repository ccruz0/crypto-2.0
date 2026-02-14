#!/usr/bin/env bash
# Regression tests for scripts/aws/check_no_inline_secrets_in_compose.sh
# Prints only short case labels (PASS case_x / FAIL case_x). No file content.
# On assertion failure: exit non-zero; checker output shows KEY@FILE only (no values).
# Run from repo root: bash tests/security/test_inline_secrets_checker.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
CHECKER="$REPO_ROOT/scripts/aws/check_no_inline_secrets_in_compose.sh"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

PASSED=0

run_check() {
  local expect_fail="${1:-0}"
  local file="$2"
  export CHECK_COMPOSE_FILE="$file"
  export DETECT_SECRET_LIKE_VALUES="${DETECT_SECRET_LIKE_VALUES:-0}"
  if bash "$CHECKER" >/dev/null 2>/dev/null; then
    [[ "$expect_fail" == "0" ]] && return 0 || return 1
  else
    [[ "$expect_fail" == "1" ]] && return 0 || return 1
  fi
}

assert_fail() {
  local case_label="$1"
  local file="$2"
  if run_check 1 "$file"; then
    echo "PASS $case_label"
    (( PASSED++ )) || true
  else
    echo "FAIL $case_label (expected checker exit 1)"
    CHECK_COMPOSE_FILE="$file" bash "$CHECKER" 2>&1 | grep -E '@' || true
    exit 1
  fi
}

assert_pass() {
  local case_label="$1"
  local file="$2"
  if run_check 0 "$file"; then
    echo "PASS $case_label"
    (( PASSED++ )) || true
  else
    echo "FAIL $case_label (expected checker exit 0)"
    exit 1
  fi
}

# --- Key-name + literal: must FAIL ---
printf 's:\n  x:\n    env:\n      API_KEY: example_value\n' > "$TMP/f1.yml"
assert_fail "case_1" "$TMP/f1.yml"

printf 's:\n  x:\n    env:\n      "API_KEY": "example_value"\n' > "$TMP/f2.yml"
assert_fail "case_2" "$TMP/f2.yml"

printf 's:\n  x:\n    env:\n      - API-KEY=dummy_value\n' > "$TMP/f3.yml"
assert_fail "case_3" "$TMP/f3.yml"

printf 's:\n  x:\n    env:\n      API_KEY:\n        REDACTED\n' > "$TMP/f4.yml"
assert_fail "case_4" "$TMP/f4.yml"

# --- Refs and allowlist: must PASS ---
printf 's:\n  x:\n    env:\n      - API_KEY: "${API_KEY}"\n' > "$TMP/p1.yml"
assert_pass "case_5" "$TMP/p1.yml"

printf 's:\n  x:\n    env:\n      - API_KEY: $API_KEY\n' > "$TMP/p2.yml"
assert_pass "case_6" "$TMP/p2.yml"

printf 's:\n  x:\n    env:\n# - API_KEY: ${API_KEY}\n      - FOO=bar\n' > "$TMP/p3.yml"
assert_pass "case_7" "$TMP/p3.yml"

printf 's:\n  x:\n    env:\n      - ENABLE_DIAGNOSTICS_ENDPOINTS=1\n' > "$TMP/p4.yml"
assert_pass "case_8" "$TMP/p4.yml"

# --- Optional: DETECT_SECRET_LIKE_VALUES=1 ---
printf 's:\n  x:\n    env:\n      - RANDOM=postgresql://example\n' > "$TMP/s1.yml"
DETECT_SECRET_LIKE_VALUES=1 assert_fail "case_9" "$TMP/s1.yml"

printf 's:\n  x:\n    env:\n      - RANDOM=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef0123456789\n' > "$TMP/s2.yml"
DETECT_SECRET_LIKE_VALUES=1 assert_fail "case_10" "$TMP/s2.yml"

printf 's:\n  x:\n    env:\n      - RANDOM=${RANDOM}\n' > "$TMP/s3.yml"
DETECT_SECRET_LIKE_VALUES=1 assert_pass "case_11" "$TMP/s3.yml"

# Self-check: expected number of cases must have passed (exit non-zero otherwise)
EXPECTED_PASS=11
if [[ $PASSED -ne $EXPECTED_PASS ]]; then
  echo "FAIL self-check: expected $EXPECTED_PASS cases passed, got $PASSED"
  exit 1
fi
echo ""
echo "All $EXPECTED_PASS regression tests passed."
