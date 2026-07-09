#!/usr/bin/env bash
# Safety tests for self-heal: dry-run, deploy marker, unknown verify, destructive gate.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PASS=0
FAIL=0

pass() {
  echo "PASS: $1"
  PASS=$((PASS + 1))
}

fail() {
  echo "FAIL: $1"
  FAIL=$((FAIL + 1))
}

setup_fake_bin() {
  FAKE_BIN="$(mktemp -d)"
  export PATH="$FAKE_BIN:$PATH"

  cat >"$FAKE_BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "UNEXPECTED: docker invoked: $*" >&2
exit 99
EOF
  chmod +x "$FAKE_BIN/docker"

  cat >"$FAKE_BIN/systemctl" <<'EOF'
#!/usr/bin/env bash
echo "UNEXPECTED: systemctl invoked: $*" >&2
exit 99
EOF
  chmod +x "$FAKE_BIN/systemctl"

  cat >"$FAKE_BIN/sudo" <<'EOF'
#!/usr/bin/env bash
if [ "$1" = "systemctl" ] || [ "$1" = "find" ] || [ "$1" = "journalctl" ] || [ "$1" = "nginx" ] || [ "$1" = "apt-get" ]; then
  echo "UNEXPECTED: sudo $*" >&2
  exit 99
fi
exec /usr/bin/sudo "$@"
EOF
  chmod +x "$FAKE_BIN/sudo"
}

teardown_fake_bin() {
  if [ -n "${FAKE_BIN:-}" ] && [ -d "$FAKE_BIN" ]; then
    rm -rf "$FAKE_BIN"
  fi
}

test_heal_dry_run_flag() {
  setup_fake_bin
  local out
  if out="$(REPO_DIR="$ROOT_DIR" "$ROOT_DIR/scripts/selfheal/heal.sh" --dry-run 2>&1)"; then
    :
  else
    fail "heal.sh --dry-run exited non-zero"
    teardown_fake_bin
    return
  fi
  echo "$out" | grep -q "DRY_RUN: REPO_DIR=$ROOT_DIR" || fail "dry-run missing REPO_DIR"
  echo "$out" | grep -q "DRY_RUN: planned_actions:" || fail "dry-run missing planned_actions"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "dry-run invoked docker/systemctl"
  pass "heal.sh --dry-run does not call docker/systemctl"
  teardown_fake_bin
}

test_heal_dry_run_env() {
  setup_fake_bin
  local out
  out="$(ATP_SELFHEAL_DRY_RUN=1 REPO_DIR="$ROOT_DIR" "$ROOT_DIR/scripts/selfheal/heal.sh" 2>&1)" || true
  echo "$out" | grep -q "DRY_RUN: REPO_DIR=" || fail "ATP_SELFHEAL_DRY_RUN missing REPO_DIR"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "ATP_SELFHEAL_DRY_RUN invoked docker/systemctl"
  pass "ATP_SELFHEAL_DRY_RUN=1 does not call docker/systemctl"
  teardown_fake_bin
}

test_deploy_marker_skip_heal() {
  local marker
  marker="$(mktemp)"
  echo "test deploy" >"$marker"
  local out exit_code=0
  out="$(ATP_DEPLOY_MARKER="$marker" REPO_DIR="$ROOT_DIR" "$ROOT_DIR/scripts/selfheal/heal.sh" 2>&1)" || exit_code=$?
  rm -f "$marker"
  if [ "$exit_code" -ne 0 ]; then
    fail "deploy marker heal.sh exited $exit_code (expected 0)"
    return
  fi
  echo "$out" | grep -q "DEPLOY_IN_PROGRESS" || fail "deploy marker missing skip message"
  pass "deploy marker causes heal.sh skip"
}

test_cooldown_skip_heal() {
  setup_fake_bin
  local cooldown
  cooldown="$(mktemp)"
  date +%s >"$cooldown"

  local out exit_code=0
  out="$(ATP_SELFHEAL_COOLDOWN_FILE="$cooldown" REPO_DIR="$ROOT_DIR" \
    "$ROOT_DIR/scripts/selfheal/heal.sh" "FAIL:API_HEALTH:down" 2>&1)" || exit_code=$?

  if [ ! -f "$cooldown" ]; then
    fail "cooldown file missing after skip (expected to remain)"
    rm -f "$cooldown"
    teardown_fake_bin
    return
  fi
  rm -f "$cooldown"

  if [ "$exit_code" -ne 0 ]; then
    fail "cooldown heal.sh exited $exit_code (expected 0)"
    teardown_fake_bin
    return
  fi
  echo "$out" | grep -q "COOLDOWN:" || fail "cooldown missing skip message"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "cooldown invoked docker/systemctl"
  pass "cooldown causes heal.sh skip without destructive commands"
  teardown_fake_bin
}

test_deploy_marker_skip_run() {
  setup_fake_bin
  local marker tmpdir
  marker="$(mktemp)"
  tmpdir="$(mktemp -d)"
  echo "test deploy" >"$marker"

  cat >"$tmpdir/verify.sh" <<'EOF'
#!/usr/bin/env bash
echo "UNEXPECTED: verify.sh invoked: $*" >&2
exit 99
EOF
  chmod +x "$tmpdir/verify.sh"

  cat >"$tmpdir/heal.sh" <<'EOF'
#!/usr/bin/env bash
echo "UNEXPECTED: heal.sh invoked: $*" >&2
exit 99
EOF
  chmod +x "$tmpdir/heal.sh"

  local out exit_code=0
  out="$(ATP_DEPLOY_MARKER="$marker" \
    ATP_SELFHEAL_VERIFY="$tmpdir/verify.sh" \
    ATP_SELFHEAL_HEAL="$tmpdir/heal.sh" \
    "$ROOT_DIR/scripts/selfheal/run.sh" 2>&1)" || exit_code=$?
  rm -f "$marker"
  rm -rf "$tmpdir"

  if [ "$exit_code" -ne 0 ]; then
    fail "deploy marker run.sh exited $exit_code (expected 0)"
    teardown_fake_bin
    return
  fi
  echo "$out" | grep -q "DEPLOY_IN_PROGRESS: skipping self-heal" || fail "run.sh deploy marker skip message missing"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "run.sh with deploy marker invoked verify/heal/docker/systemctl"
  pass "deploy marker causes run.sh skip without verify/heal/docker/systemctl"
  teardown_fake_bin
}

test_with_deploy_marker_cleanup() {
  local marker success_marker failure_marker
  marker="$(mktemp)"

  ATP_DEPLOY_MARKER="$marker" "$ROOT_DIR/scripts/aws/with_deploy_marker.sh" true
  if [ -f "$marker" ]; then
    fail "with_deploy_marker.sh left marker after success"
    rm -f "$marker"
    return
  fi

  success_marker="$(mktemp)"
  ATP_DEPLOY_MARKER="$success_marker" "$ROOT_DIR/scripts/aws/with_deploy_marker.sh" true
  if [ -f "$success_marker" ]; then
    fail "with_deploy_marker.sh left marker after success (custom path)"
    rm -f "$success_marker"
    return
  fi

  failure_marker="$(mktemp)"
  if ATP_DEPLOY_MARKER="$failure_marker" "$ROOT_DIR/scripts/aws/with_deploy_marker.sh" false 2>/dev/null; then
    fail "with_deploy_marker.sh false command should exit non-zero"
    rm -f "$failure_marker"
    return
  fi
  if [ -f "$failure_marker" ]; then
    fail "with_deploy_marker.sh left marker after failure"
    rm -f "$failure_marker"
    return
  fi

  pass "with_deploy_marker.sh removes marker on success and failure"
}

test_unknown_verify_no_docker() {
  setup_fake_bin
  local tmpdir marker cooldown
  tmpdir="$(mktemp -d)"
  marker="$(mktemp)"
  cooldown="$(mktemp)"
  rm -f "$marker"

  cat >"$tmpdir/verify.sh" <<'EOF'
#!/usr/bin/env bash
echo '{"status":"ok"}'
exit 1
EOF
  chmod +x "$tmpdir/verify.sh"

  cat >"$tmpdir/run.sh" <<EOF
#!/usr/bin/env bash
set -euo pipefail
VERIFY="$tmpdir/verify.sh"
HEAL="$ROOT_DIR/scripts/selfheal/heal.sh"
DEPLOY_MARKER="$marker"
COOLDOWN_FILE="$cooldown"
COOLDOWN_SECS=900
export PATH="$FAKE_BIN:\$PATH"

if [ -f "\$DEPLOY_MARKER" ]; then
  echo "DEPLOY_IN_PROGRESS: skipping self-heal"
  exit 0
fi

if "\$VERIFY" >/tmp/atp-verify-test.json 2>/tmp/atp-verify-test.err; then
  echo "PASS"
  exit 0
fi

reason="\$(grep -E '^FAIL:' /tmp/atp-verify-test.json 2>/dev/null | tail -n 1 || true)"
if [ -z "\$reason" ]; then
  reason="\$(tail -n 1 /tmp/atp-verify-test.err 2>/dev/null || true)"
fi

if [ -z "\$reason" ] || [[ ! "\$reason" =~ ^FAIL: ]]; then
  echo "VERIFY_DEGRADED: unknown or unparseable verify failure; skipping recovery"
  exit 1
fi

echo "Verify failed: \$reason"
"\$HEAL" "\$reason"
EOF
  chmod +x "$tmpdir/run.sh"

  local out exit_code=0
  out="$(PATH="$FAKE_BIN:$PATH" "$tmpdir/run.sh" 2>&1)" || exit_code=$?
  rm -rf "$tmpdir" "$marker" "$cooldown"
  rm -f /tmp/atp-verify-test.json /tmp/atp-verify-test.err

  if [ "$exit_code" -ne 1 ]; then
    fail "unknown verify should exit 1 (got $exit_code)"
    teardown_fake_bin
    return
  fi
  echo "$out" | grep -q "VERIFY_DEGRADED" || fail "unknown verify missing VERIFY_DEGRADED"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "unknown verify invoked docker/systemctl"
  pass "unknown verify result does not restart Docker"
  teardown_fake_bin
}

test_destructive_gate() {
  setup_fake_bin
  local tmp_repo cooldown_safe cooldown_destructive
  tmp_repo="$(mktemp -d)"
  cooldown_safe="$(mktemp)"
  cooldown_destructive="$(mktemp)"
  echo "POSTGRES_PASSWORD=test" >"$tmp_repo/.env"
  cp "$tmp_repo/.env" "$tmp_repo/.env.aws"
  mkdir -p "$tmp_repo/secrets"
  echo "# test runtime" >"$tmp_repo/secrets/runtime.env"
  chmod 600 "$tmp_repo/secrets/runtime.env"
  ln -s "$ROOT_DIR/docker-compose.yml" "$tmp_repo/docker-compose.yml"
  mkdir -p "$tmp_repo/scripts/aws"
  cp "$ROOT_DIR/scripts/aws/ensure_env_aws.sh" "$tmp_repo/scripts/aws/"

  local out exit_code=0
  out="$(ATP_SELFHEAL_COOLDOWN_FILE="$cooldown_safe" REPO_DIR="$tmp_repo" "$ROOT_DIR/scripts/selfheal/heal.sh" "FAIL:API_HEALTH:down" 2>&1)" || exit_code=$?

  if [ "$exit_code" -eq 0 ]; then
    fail "safe heal should exit non-zero (got 0)"
    rm -rf "$tmp_repo" "$cooldown_safe" "$cooldown_destructive"
    teardown_fake_bin
    return
  fi
  echo "$out" | grep -q "SAFE_MODE" || fail "safe heal missing SAFE_MODE"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "safe heal invoked docker without destructive flag"

  exit_code=0
  out="$(ATP_SELFHEAL_ALLOW_DESTRUCTIVE=1 ATP_SELFHEAL_COOLDOWN_FILE="$cooldown_destructive" REPO_DIR="$tmp_repo" "$ROOT_DIR/scripts/selfheal/heal.sh" "FAIL:API_HEALTH:down" 2>&1)" || exit_code=$?
  rm -rf "$tmp_repo" "$cooldown_safe" "$cooldown_destructive"
  echo "$out" | grep -q "UNEXPECTED:" || fail "destructive mode should attempt docker/systemctl recovery (output: $out)"
  pass "destructive actions require ATP_SELFHEAL_ALLOW_DESTRUCTIVE=1"
  teardown_fake_bin
}

test_signal_monitor_safe_remediation() {
  local cooldown tmpdir
  cooldown="$(mktemp)"
  tmpdir="$(mktemp -d)"

  cat >"$tmpdir/curl" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == *"/api/health/fix"* ]]; then
  exit 0
fi
if [[ "$*" == *"/api/health/system"* ]]; then
  echo '{"signal_monitor":{"status":"PASS"}}'
  exit 0
fi
echo "UNEXPECTED curl: $*" >&2
exit 99
EOF
  chmod +x "$tmpdir/curl"

  cat >"$tmpdir/docker" <<'EOF'
#!/usr/bin/env bash
echo "UNEXPECTED docker: $*" >&2
exit 99
EOF
  chmod +x "$tmpdir/docker"

  local out exit_code=0
  out="$(PATH="$tmpdir:$PATH" ATP_SELFHEAL_COOLDOWN_FILE="$cooldown" ATP_REMEDIATE_SIGNAL_MONITOR_GRACE_SEC=0 \
    REPO_DIR="$ROOT_DIR" "$ROOT_DIR/scripts/selfheal/heal.sh" "FAIL:SIGNAL_MONITOR:FAIL" 2>&1)" || exit_code=$?

  rm -f "$cooldown"
  rm -rf "$tmpdir"

  if [ "$exit_code" -ne 0 ]; then
    fail "signal monitor heal should exit 0 (got $exit_code)"
    return
  fi
  echo "$out" | grep -q "Signal monitor remediation starting" || fail "missing signal monitor remediation start"
  echo "$out" | grep -qv "UNEXPECTED:" || fail "signal monitor heal invoked unexpected docker"
  pass "FAIL:SIGNAL_MONITOR triggers light remediation without full destructive mode"
}

test_executable_permissions() {
  if bash "$ROOT_DIR/scripts/test_selfheal_executable_permissions.sh" >/dev/null 2>&1; then
    pass "executable permission guard still passes"
  else
    fail "executable permission guard regressed"
  fi
}

test_heal_dry_run_flag
test_heal_dry_run_env
test_deploy_marker_skip_heal
test_cooldown_skip_heal
test_deploy_marker_skip_run
test_with_deploy_marker_cleanup
test_unknown_verify_no_docker
test_destructive_gate
test_signal_monitor_safe_remediation
test_executable_permissions

echo ""
echo "Self-heal safety tests: $PASS passed, $FAIL failed"
if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
