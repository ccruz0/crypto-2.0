#!/usr/bin/env bash
# Run on EC2 from repo root. Verifies exchange_sync Decimal fix and gunicorn max-requests.
# Exit 0 on pass, non-zero on fail.

set -e
REPO="${REPO:-/home/ubuntu/automated-trading-platform}"
cd "$REPO"

echo "=== 1) Repo dir ==="
pwd

echo ""
echo "=== 2) Backend container ==="
BACKEND_CONTAINER="$(docker ps --format '{{.Names}}' | grep -E 'backend-aws' | head -n 1)"
echo "BACKEND_CONTAINER=$BACKEND_CONTAINER"
if [ -z "$BACKEND_CONTAINER" ]; then
  echo "No backend-aws container running."
  exit 1
fi

echo ""
echo "=== 3) delta_qty block (lines 1995-2030) from /app/app/services/exchange_sync.py ==="
DELTA_BLOCK="$(docker exec "$BACKEND_CONTAINER" sed -n '1995,2030p' /app/app/services/exchange_sync.py)"
echo "$DELTA_BLOCK"

echo ""
echo "=== 4) PID 1 cmdline ==="
PID1_CMDLINE="$(docker exec "$BACKEND_CONTAINER" sh -c 'cat /proc/1/cmdline 2>/dev/null | tr "\0" " "' 2>/dev/null || true)"
echo "$PID1_CMDLINE"
echo ""

echo ""
echo "=== 5) Gunicorn process cmdline (scan /proc/*/cmdline for process containing gunicorn) ==="
PROC_SCAN="$(docker exec "$BACKEND_CONTAINER" sh -c 'for p in /proc/[0-9]*; do [ -r "$p/cmdline" ] || continue; cat "$p/cmdline" 2>/dev/null | tr "\0" " "; echo; done' 2>/dev/null || true)"
GUNICORN_CMDLINE="$(echo "$PROC_SCAN" | grep "gunicorn" | head -1)"
if [ -n "$GUNICORN_CMDLINE" ]; then
  echo "$GUNICORN_CMDLINE"
else
  echo "(no gunicorn process found in /proc scan; will use PID 1 for max-requests check)"
  GUNICORN_CMDLINE="$PID1_CMDLINE"
fi
echo ""

echo ""
echo "=== 6) Last 60m logs: unsupported operand type(s) for - ==="
LOG60="$(docker logs "$BACKEND_CONTAINER" --since 60m 2>&1)"
echo "$LOG60" | grep -n "unsupported operand type(s) for -" || true

FAIL=0

if echo "$DELTA_BLOCK" | grep -q "delta_qty = float("; then
  echo "FAIL: delta_qty uses float (expected Decimal subtraction)."
  FAIL=1
fi

if ! echo "$DELTA_BLOCK" | grep -q "delta_qty = new_cumulative_qty - last_seen_qty"; then
  echo "FAIL: delta_qty block does not contain 'delta_qty = new_cumulative_qty - last_seen_qty'."
  FAIL=1
fi

if ! echo "$GUNICORN_CMDLINE" | grep -q -- "--max-requests 10000"; then
  echo "FAIL: gunicorn cmdline does not contain '--max-requests 10000'."
  FAIL=1
fi

if echo "$LOG60" | grep -q "unsupported operand type(s) for -"; then
  echo "FAIL: Logs contain 'unsupported operand type(s) for -'."
  FAIL=1
fi

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi

echo "=== Verification passed. ==="
exit 0
