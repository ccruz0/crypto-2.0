#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Deploy resiliency tests.
#
# Validates the production-safety guarantee added to fix the PR #70 incident:
# a deploy interrupted between "compose down" and "compose up -d" must NOT be
# able to leave production offline. The fix removes `compose down` before the
# build and adds an idempotent recovery (ensure_stack_up.sh) plus deploy-marker
# TTL handling in self-heal.
#
# These tests are hermetic: no real docker, AWS, or network access. Docker /
# curl / compose are stubbed via PATH and a temp repo.
#
# Scenario coverage (per task):
#   1. normal deployment            -> build precedes up; no down
#   2. failure before compose       -> no down anywhere -> old stack survives
#   3. failure after image build    -> no down before up -> old stack survives
#   4. failure before compose up    -> ensure_stack_up brings stack up, no down
#   5. verification failure         -> ensure_stack_up reports UNHEALTHY + cmd
#   6. rerun after interruption     -> ensure_stack_up idempotent (healthy=no-op)
#   7. rollback / recovery          -> ensure_stack_up reconciles to up
# ---------------------------------------------------------------------------
set -uo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PASS=0
FAIL=0
pass() { echo "PASS: $1"; PASS=$((PASS + 1)); }
fail() { echo "FAIL: $1"; FAIL=$((FAIL + 1)); }

WF="$ROOT_DIR/.github/workflows/deploy_session_manager.yml"
ENSURE="$ROOT_DIR/scripts/aws/ensure_stack_up.sh"

# ---------------------------------------------------------------------------
# Static guarantees on the deploy workflow + manual deploy mirror.
# ---------------------------------------------------------------------------
test_no_compose_down_in_deploy_paths() {
  local bad=0 f
  for f in "$WF" "$ROOT_DIR/deploy_all.sh"; do
    if grep -E 'compose .*--profile aws down|profile aws down|compose .* down( |$|\\)' "$f" >/dev/null 2>&1; then
      fail "found a 'docker compose ... down' in deploy path: $f"
      grep -nE 'down' "$f" | grep -i compose || true
      bad=1
    fi
  done
  [ "$bad" -eq 0 ] && pass "no 'docker compose down' in deploy_session_manager.yml or deploy_all.sh"
}

test_ensure_stack_up_never_downs() {
  if grep -E 'compose .* down|profile aws down| down -' "$ENSURE" >/dev/null 2>&1; then
    fail "ensure_stack_up.sh must never call 'compose down'"
  else
    pass "ensure_stack_up.sh never calls 'compose down'"
  fi
}

test_build_precedes_up_in_workflow() {
  local build_line up_line
  build_line="$(grep -n 'profile aws build --no-cache' "$WF" | head -1 | cut -d: -f1)"
  up_line="$(grep -n 'profile aws up -d --remove-orphans' "$WF" | head -1 | cut -d: -f1)"
  if [ -z "$build_line" ] || [ -z "$up_line" ]; then
    fail "workflow missing build (--no-cache) and/or 'up -d --remove-orphans' (build=$build_line up=$up_line)"
    return
  fi
  if [ "$build_line" -lt "$up_line" ]; then
    pass "workflow builds new images before 'up -d' (build@$build_line < up@$up_line)"
  else
    fail "workflow 'up -d' is not after build (build@$build_line up@$up_line)"
  fi
}

test_prune_after_up_in_workflow() {
  local up_line prune_line
  up_line="$(grep -n 'profile aws up -d --remove-orphans' "$WF" | head -1 | cut -d: -f1)"
  prune_line="$(grep -n 'docker image prune' "$WF" | head -1 | cut -d: -f1)"
  if [ -n "$up_line" ] && [ -n "$prune_line" ] && [ "$prune_line" -gt "$up_line" ]; then
    pass "image prune happens AFTER 'up -d' (up@$up_line < prune@$prune_line)"
  else
    fail "image prune should be after 'up -d' (up@$up_line prune@$prune_line)"
  fi
}

test_workflow_has_recovery_command() {
  if grep -q 'ensure_stack_up.sh' "$WF"; then
    pass "workflow invokes ensure_stack_up.sh as a recovery net"
  else
    fail "workflow does not invoke ensure_stack_up.sh"
  fi
}

# ---------------------------------------------------------------------------
# Functional tests for ensure_stack_up.sh in a stubbed temp repo.
# ---------------------------------------------------------------------------
make_stub_repo() {
  local repo="$1" calls="$2" upflag="$3"
  mkdir -p "$repo/scripts/aws"
  : >"$repo/docker-compose.yml"
  cp "$ENSURE" "$repo/scripts/aws/ensure_stack_up.sh"
  chmod +x "$repo/scripts/aws/ensure_stack_up.sh"

  # Stub prod_compose.sh: records args; "up" creates the upflag so the stub
  # curl can start reporting healthy. "ps" prints a fake line.
  cat >"$repo/scripts/aws/prod_compose.sh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$calls"
case "\$1" in
  up) : > "$upflag" ; echo "Creating ... done" ; exit 0 ;;
  ps) echo "backend-aws  Up" ; exit 0 ;;
  *)  exit 0 ;;
esac
EOF
  chmod +x "$repo/scripts/aws/prod_compose.sh"

  cat >"$repo/scripts/aws/render_runtime_env.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$repo/scripts/aws/render_runtime_env.sh"

  cat >"$repo/scripts/aws/export_build_fingerprint.sh" <<'EOF'
#!/usr/bin/env bash
exit 0
EOF
  chmod +x "$repo/scripts/aws/export_build_fingerprint.sh"
}

# Fake curl: healthy iff the upflag file exists OR FORCE_HEALTHY=1.
make_fake_bin() {
  local fakebin="$1" upflag="$2"
  mkdir -p "$fakebin"
  cat >"$fakebin/curl" <<EOF
#!/usr/bin/env bash
if [ "\${FORCE_HEALTHY:-0}" = "1" ] || [ -f "$upflag" ]; then
  exit 0
fi
exit 7
EOF
  chmod +x "$fakebin/curl"
}

test_ensure_healthy_is_noop() {
  local tmp repo calls upflag fakebin out rc=0
  tmp="$(mktemp -d)"; repo="$tmp/repo"; calls="$tmp/calls"; upflag="$tmp/upflag"; fakebin="$tmp/bin"
  : >"$calls"
  make_stub_repo "$repo" "$calls" "$upflag"
  make_fake_bin "$fakebin" "$upflag"

  out="$(PATH="$fakebin:$PATH" FORCE_HEALTHY=1 ATP_DEPLOY_MARKER="$tmp/marker" \
    ATP_SELFHEAL_LOCK="$tmp/lock" ENSURE_STACK_PROBE_RETRIES=1 \
    ENSURE_STACK_WAIT_ITERS=1 ENSURE_STACK_WAIT_INTERVAL=0 \
    "$repo/scripts/aws/ensure_stack_up.sh" 2>&1)" || rc=$?

  if [ "$rc" -ne 0 ]; then fail "healthy no-op should exit 0 (got $rc): $out"; rm -rf "$tmp"; return; fi
  echo "$out" | grep -q "RESULT: HEALTHY (no-op)" || fail "healthy run missing 'HEALTHY (no-op)'"
  if grep -q '^up' "$calls"; then
    fail "healthy run must NOT call 'compose up' (calls: $(cat "$calls"))"
  else
    pass "ensure_stack_up is a no-op when backend already healthy (scenario 6 rerun)"
  fi
  rm -rf "$tmp"
}

test_ensure_unhealthy_recovers_without_down() {
  local tmp repo calls upflag fakebin out rc=0
  tmp="$(mktemp -d)"; repo="$tmp/repo"; calls="$tmp/calls"; upflag="$tmp/upflag"; fakebin="$tmp/bin"
  : >"$calls"
  make_stub_repo "$repo" "$calls" "$upflag"
  make_fake_bin "$fakebin" "$upflag"
  # upflag absent initially -> first health check fails -> triggers up -> up creates upflag -> healthy

  out="$(PATH="$fakebin:$PATH" ATP_DEPLOY_MARKER="$tmp/marker" \
    ATP_SELFHEAL_LOCK="$tmp/lock" ENSURE_STACK_PROBE_RETRIES=1 \
    ENSURE_STACK_WAIT_ITERS=3 ENSURE_STACK_WAIT_INTERVAL=0 \
    "$repo/scripts/aws/ensure_stack_up.sh" 2>&1)" || rc=$?

  if [ "$rc" -ne 0 ]; then fail "recovery should exit 0 after up (got $rc): $out"; rm -rf "$tmp"; return; fi
  echo "$out" | grep -q "RESULT: HEALTHY (recovered)" || fail "recovery run missing 'HEALTHY (recovered)'"
  if grep -qE '^up -d --remove-orphans' "$calls"; then
    pass "ensure_stack_up recovers via 'up -d --remove-orphans' (scenarios 4 & 7)"
  else
    fail "recovery did not call 'up -d --remove-orphans' (calls: $(cat "$calls"))"
  fi
  if grep -qi 'down' "$calls"; then
    fail "recovery must never call 'down' (calls: $(cat "$calls"))"
  fi
  rm -rf "$tmp"
}

test_ensure_unhealthy_persists_reports_recovery_cmd() {
  local tmp repo calls upflag fakebin out rc=0
  tmp="$(mktemp -d)"; repo="$tmp/repo"; calls="$tmp/calls"; upflag="$tmp/upflag"; fakebin="$tmp/bin"
  : >"$calls"
  make_stub_repo "$repo" "$calls" "$upflag"
  # Fake curl that is ALWAYS unhealthy (ignore upflag) to simulate a real fault.
  mkdir -p "$fakebin"
  cat >"$fakebin/curl" <<'EOF'
#!/usr/bin/env bash
exit 7
EOF
  chmod +x "$fakebin/curl"
  # prod_compose "up" must still succeed but health never comes up.
  cat >"$repo/scripts/aws/prod_compose.sh" <<EOF
#!/usr/bin/env bash
echo "\$*" >> "$calls"
[ "\$1" = "ps" ] && echo "backend-aws  Restarting"
exit 0
EOF
  chmod +x "$repo/scripts/aws/prod_compose.sh"

  out="$(PATH="$fakebin:$PATH" ATP_DEPLOY_MARKER="$tmp/marker" \
    ATP_SELFHEAL_LOCK="$tmp/lock" ENSURE_STACK_PROBE_RETRIES=1 \
    ENSURE_STACK_WAIT_ITERS=2 ENSURE_STACK_WAIT_INTERVAL=0 \
    "$repo/scripts/aws/ensure_stack_up.sh" 2>&1)" || rc=$?

  if [ "$rc" -eq 0 ]; then fail "persistent fault should exit non-zero (scenario 5)"; rm -rf "$tmp"; return; fi
  echo "$out" | grep -q "RESULT: UNHEALTHY" || fail "persistent fault missing 'RESULT: UNHEALTHY'"
  echo "$out" | grep -q "RECOMMENDED_RECOVERY:" || fail "persistent fault missing recovery command"
  pass "ensure_stack_up reports UNHEALTHY + recovery command on persistent fault (scenario 5)"
  rm -rf "$tmp"
}

# ---------------------------------------------------------------------------
# Deploy-marker TTL handling in self-heal (closes the "stale marker disables
# self-heal forever" gap from the incident).
# ---------------------------------------------------------------------------
test_with_deploy_marker_writes_epoch() {
  local tmp marker
  tmp="$(mktemp -d)"; marker="$tmp/marker"
  # Marker only exists while the wrapped command runs; capture it via the command.
  ATP_DEPLOY_MARKER="$marker" "$ROOT_DIR/scripts/aws/with_deploy_marker.sh" \
    bash -c "grep -q '^epoch=[0-9]' '$marker' || exit 3"
  local rc=$?
  rm -rf "$tmp"
  if [ "$rc" -eq 0 ]; then
    pass "with_deploy_marker.sh writes a parseable 'epoch=' line"
  else
    fail "with_deploy_marker.sh marker missing 'epoch=' (rc=$rc)"
  fi
}

run_selfheal_run() {
  # helper: run scripts/selfheal/run.sh with stub verify/heal
  local marker="$1"; shift
  local tmp; tmp="$(mktemp -d)"
  cat >"$tmp/verify.sh" <<'EOF'
#!/usr/bin/env bash
echo "PASS"
exit 0
EOF
  cat >"$tmp/heal.sh" <<'EOF'
#!/usr/bin/env bash
echo "HEAL_CALLED"
exit 0
EOF
  chmod +x "$tmp/verify.sh" "$tmp/heal.sh"
  ATP_DEPLOY_MARKER="$marker" \
    ATP_SELFHEAL_VERIFY="$tmp/verify.sh" \
    ATP_SELFHEAL_HEAL="$tmp/heal.sh" \
    ATP_SELFHEAL_COOLDOWN_FILE="$tmp/cooldown" \
    "$ROOT_DIR/scripts/selfheal/run.sh" 2>&1
  local rc=$?
  rm -rf "$tmp"
  return $rc
}

test_fresh_marker_blocks_selfheal() {
  local tmp marker out rc=0
  tmp="$(mktemp -d)"; marker="$tmp/marker"
  echo "epoch=$(date +%s) pid=1" >"$marker"
  out="$(run_selfheal_run "$marker")" || rc=$?
  rm -rf "$tmp"
  if echo "$out" | grep -q "DEPLOY_IN_PROGRESS" && [ "$rc" -eq 0 ]; then
    pass "fresh deploy marker blocks self-heal (DEPLOY_IN_PROGRESS)"
  else
    fail "fresh marker should block self-heal (rc=$rc out=$out)"
  fi
}

test_stale_marker_unblocks_selfheal() {
  local tmp marker out rc=0
  tmp="$(mktemp -d)"; marker="$tmp/marker"
  echo "epoch=1 pid=1" >"$marker"   # epoch=1 (1970) -> always stale
  out="$(run_selfheal_run "$marker")" || rc=$?
  local existed=1; [ -f "$marker" ] && existed=0
  rm -rf "$tmp"
  if echo "$out" | grep -q "STALE_DEPLOY_MARKER" && echo "$out" | grep -q "PASS"; then
    if [ "$existed" -ne 0 ]; then
      pass "stale deploy marker is removed and self-heal proceeds (incident gap closed)"
    else
      fail "stale marker should be removed after run.sh"
    fi
  else
    fail "stale marker should unblock self-heal (rc=$rc out=$out)"
  fi
}

test_no_compose_down_in_deploy_paths
test_ensure_stack_up_never_downs
test_build_precedes_up_in_workflow
test_prune_after_up_in_workflow
test_workflow_has_recovery_command
test_ensure_healthy_is_noop
test_ensure_unhealthy_recovers_without_down
test_ensure_unhealthy_persists_reports_recovery_cmd
test_with_deploy_marker_writes_epoch
test_fresh_marker_blocks_selfheal
test_stale_marker_unblocks_selfheal

echo ""
echo "Deploy resiliency tests: $PASS passed, $FAIL failed"
[ "$FAIL" -eq 0 ]
