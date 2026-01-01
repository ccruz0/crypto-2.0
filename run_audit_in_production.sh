#!/bin/bash
# Run audit script in production (AWS container)
# This script helps you run the audit and view results

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "🔍 Running Audit in Production"
echo "=============================="
echo ""

# Check if backend-aws container is running
if ! docker compose --profile aws ps backend-aws | grep -q "Up"; then
    echo "❌ Error: backend-aws container is not running"
    echo "   Start it with: docker compose --profile aws up -d backend-aws"
    exit 1
fi

# Parse arguments
SINCE_HOURS="${1:-168}"
SYMBOLS="${2:-}"
OUTPUT="${3:-docs/reports/no-alerts-no-trades-audit.md}"

echo "📋 Audit Configuration:"
echo "  - Since hours: $SINCE_HOURS"
if [ -n "$SYMBOLS" ]; then
    echo "  - Symbols: $SYMBOLS"
else
    echo "  - Symbols: All (not specified)"
fi
echo "  - Output: $OUTPUT"
echo ""

# Build command
CMD="python backend/scripts/audit_no_alerts_no_trades.py --since-hours $SINCE_HOURS"
if [ -n "$SYMBOLS" ]; then
    CMD="$CMD --symbols $SYMBOLS"
fi
CMD="$CMD --output $OUTPUT"

echo "🚀 Running audit..."
echo ""

# Run audit in container
docker exec backend-aws $CMD

echo ""
echo "✅ Audit complete!"
echo ""
echo "📄 Report generated at: $OUTPUT"
echo ""
echo "📊 Quick summary:"
docker exec backend-aws cat "$OUTPUT" | grep -A 5 "GLOBAL STATUS" || echo "  (Check report file for details)"
echo ""
echo "💡 Next steps:"
echo "  1. Review the report: $OUTPUT"
echo "  2. Check root causes section"
echo "  3. Apply recommended fixes"
echo "  4. Re-run audit to verify fixes"
echo ""

