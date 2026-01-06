#!/bin/bash
# Portfolio Reconcile Evidence Collection Script
# Safe - only prints numeric values and field paths (no secrets)

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO_ROOT"

# Create evidence directory
ts=$(date -u +"%Y-%m-%dT%H-%M-%SZ")
out="evidence/portfolio_reconcile/$ts"
mkdir -p "$out"

echo "📊 Portfolio Reconcile Evidence Collection"
echo "   Output: $out"
echo ""

# Step 1: Verify backend health
echo "1️⃣  Verifying backend health..."
if curl -sS "http://localhost:8002/ping_fast" > /dev/null 2>&1; then
    echo "   ✅ Backend is responding"
else
    echo "   ❌ Backend not responding at http://localhost:8002"
    echo "   Please ensure SSM port-forward is active or backend is running"
    exit 1
fi

# Step 2: Fetch dashboard state
echo ""
echo "2️⃣  Fetching dashboard state..."
if curl -sS "http://localhost:8002/api/dashboard/state" > "$out/dashboard_state.json" 2>&1; then
    # Check if response is valid JSON
    if python3 -c "import json; json.load(open('$out/dashboard_state.json'))" 2>/dev/null; then
        echo "   ✅ Dashboard state fetched successfully"
    else
        echo "   ⚠️  Response is not valid JSON (may be error page)"
        echo "   Response preview:"
        head -5 "$out/dashboard_state.json"
        echo ""
        echo "   Backend may need PORTFOLIO_RECONCILE_DEBUG=1 enabled"
        exit 1
    fi
else
    echo "   ❌ Failed to fetch dashboard state"
    exit 1
fi

# Step 3: Extract portfolio evidence
echo ""
echo "3️⃣  Extracting portfolio evidence..."
if [ -f "evidence/portfolio_reconcile/extract_portfolio.py" ]; then
    python3 evidence/portfolio_reconcile/extract_portfolio.py "$out/dashboard_state.json" "$out"
    echo "   ✅ Evidence extracted"
else
    echo "   ⚠️  extract_portfolio.py not found, skipping extraction"
fi

# Step 4: Print summary
echo ""
echo "4️⃣  Summary:"
echo "   Evidence folder: $out"
python3 << PYEOF
import json
import sys
from pathlib import Path

out_path = Path("$out")
dashboard_path = out_path / "dashboard_state.json"

if dashboard_path.exists():
    with open(dashboard_path) as f:
        data = json.load(f)
    
    portfolio = data.get('portfolio', {})
    if portfolio:
        print(f"   total_value_usd: {portfolio.get('total_value_usd')}")
        print(f"   portfolio_value_source: {portfolio.get('portfolio_value_source')}")
        
        reconcile = portfolio.get('reconcile')
        if reconcile:
            chosen = reconcile.get('chosen', {})
            if chosen:
                print(f"   reconcile.chosen.field_path: {chosen.get('field_path')}")
                print(f"   reconcile.chosen.value: {chosen.get('value')}")
                print(f"   reconcile.chosen.priority: {chosen.get('priority')}")
            
            # Show filtered raw_fields (top 10)
            raw_fields = reconcile.get('raw_fields', {})
            if raw_fields:
                keywords = ["wallet", "balance", "equity", "haircut", "total", "net", "margin"]
                filtered = {
                    k: v for k, v in raw_fields.items()
                    if any(kw in k.lower() for kw in keywords) and isinstance(v, (int, float))
                }
                print(f"\n   Filtered raw_fields (top 10):")
                for key, value in list(sorted(filtered.items()))[:10]:
                    print(f"     {key}: ${value:,.2f}")
        else:
            print("   ⚠️  reconcile data not present (PORTFOLIO_RECONCILE_DEBUG=1 may not be enabled)")
    else:
        print("   ⚠️  No portfolio data in response")
else:
    print("   ❌ dashboard_state.json not found")
PYEOF

echo ""
echo "✅ Evidence collection complete!"
echo "   Files saved to: $out"
