#!/usr/bin/env bash
# Nightly integrity audit: fail fast; send exactly one Telegram alert on first failing step.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

send_audit_failure() {
  local step="$1"
  docker compose --profile aws exec -T backend-aws python3 -c "
import sys
step = sys.argv[1] if len(sys.argv) > 1 else 'unknown'
try:
    from app.services.telegram_notifier import telegram_notifier
    telegram_notifier.send_message('Nightly integrity audit FAILED: ' + step)
except Exception as e:
    print(str(e), file=sys.stderr)
    sys.exit(0)
" "$step" 2>/dev/null || true
}

if ! bash "$SCRIPT_DIR/reconcile_order_intents.sh"; then
  send_audit_failure "reconcile_order_intents"
  echo "FAIL"
  exit 1
fi

if ! bash "$SCRIPT_DIR/portfolio_consistency_check.sh"; then
  send_audit_failure "portfolio_consistency_check"
  echo "FAIL"
  exit 1
fi

echo "PASS"
exit 0
