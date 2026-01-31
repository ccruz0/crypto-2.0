#!/usr/bin/env bash
# Run trigger probe for ETH_USDT with side SELL and BUY; save logs and print key summary lines.
set -euo pipefail

cd /Users/carloscruz/automated-trading-platform

INSTRUMENT="${INSTRUMENT:-ETH_USDT}"
QTY="${QTY:-0.003}"
REF_PRICE="${REF_PRICE:-2950}"
MAX_VARIANTS="${MAX_VARIANTS:-50}"
TS=$(date +%Y%m%d_%H%M%S)
JSONL_PATHS=()

for SIDE in SELL BUY; do
  LOG="/tmp/trigger_probe_matrix_${SIDE}_${TS}.log"
  echo "=== Run probe side=${SIDE} -> ${LOG} ==="
  PYTHONPATH=backend python3 -m app.tools.crypto_com_trigger_probe \
    --instrument "$INSTRUMENT" \
    --side "$SIDE" \
    --qty "$QTY" \
    --ref-price "$REF_PRICE" \
    --max-variants "$MAX_VARIANTS" \
    2>&1 | tee "$LOG"
  echo ""
  echo "--- Extracted from ${LOG} ---"
  grep -E "correlation_id:|jsonl_path:" "$LOG" || true
  grep -A 15 "Group counts by (http_status, code, message):" "$LOG" | head -20 || true
  grep -E "ORDER_ID_BUT_REJECTED \(code=220\)|filtered_invalid_side_rule:" "$LOG" || true
  JPATH=$(grep '^jsonl_path:' "$LOG" | awk '{print $2}')
  if [[ -n "${JPATH:-}" ]]; then
    JSONL_PATHS+=("$JPATH")
  fi
  echo ""
done

echo "=== JSONL files from this run ==="
for p in "${JSONL_PATHS[@]}"; do
  echo "$p"
done
