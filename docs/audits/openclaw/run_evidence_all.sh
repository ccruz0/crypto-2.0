#!/usr/bin/env bash
# Run all OpenClaw evidence commands (PR1–PR6) and write timestamped logs.
# Fail fast on first failure. Run from repo root.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
cd "$REPO_ROOT"
LOG_DIR="docs/audits/openclaw/EVIDENCE/logs"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

run() {
  local name="$1"
  shift
  echo "=== $name ==="
  python3 -m pytest "$@" -v --tb=short 2>&1 | tee "$LOG_DIR/${name}_${STAMP}.txt"
}

echo "Evidence run started at $(date -Iseconds)"
echo "Logs: $LOG_DIR"
echo ""

run "pr-01" backend/tests/test_redaction.py backend/tests/test_no_secret_logging_strings.py
run "pr-02" backend/tests/test_sync_missing_not_canceled.py
run "pr-03" backend/tests/test_terminal_order_notifier.py
run "pr-04" backend/tests/test_trade_blocked_reason_codes.py
run "pr-05" backend/tests/test_stale_data_gate.py
run "pr-06" backend/tests/test_system_contracts.py backend/tests/test_stale_data_gate.py

echo ""
echo "All evidence runs passed. Logs in $LOG_DIR"
