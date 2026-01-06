#!/usr/bin/env python3
"""Analyze portfolio reconcile data to identify which field matches Crypto.com UI Balance"""
import json
import sys

if len(sys.argv) < 2:
    print("Usage: python3 analyze_reconcile.py <dashboard_state.json>")
    sys.exit(1)

with open(sys.argv[1], 'r') as f:
    data = json.load(f)

portfolio = data.get('portfolio', {})
reconcile = portfolio.get('reconcile', {})

print("=== Portfolio Summary ===")
print(f"total_value_usd: ${portfolio.get('total_value_usd', 0):,.2f}")
print(f"portfolio_value_source: {portfolio.get('portfolio_value_source', 'N/A')}")
print(f"total_assets_usd: ${portfolio.get('total_assets_usd', 0):,.2f}")
print(f"total_collateral_usd: ${portfolio.get('total_collateral_usd', 0):,.2f}")
print(f"total_borrowed_usd: ${portfolio.get('total_borrowed_usd', 0):,.2f}")

print("\n=== Reconcile Data ===")
if reconcile:
    print(f"Reconcile present: Yes")
    
    raw_fields = reconcile.get('raw_fields', {})
    candidates = reconcile.get('candidates', {})
    chosen = reconcile.get('chosen', {})
    
    print(f"\nRaw Fields ({len(raw_fields)}):")
    for key, value in sorted(raw_fields.items()):
        if isinstance(value, (int, float)):
            print(f"  {key}: ${value:,.2f}")
        else:
            print(f"  {key}: {value}")
    
    print(f"\nCandidates ({len(candidates)}):")
    for key, value in sorted(candidates.items()):
        print(f"  {key}: ${value:,.2f}")
    
    print(f"\nChosen:")
    if chosen:
        print(f"  value: ${chosen.get('value', 0):,.2f}")
        print(f"  source: {chosen.get('source', 'N/A')}")
        print(f"  priority: {chosen.get('priority', 'N/A')}")
    
    # Analysis: Find values close to UI Balance (~11,511.49)
    ui_balance_target = 11511.49
    print(f"\n=== Analysis: Values near UI Balance (${ui_balance_target:,.2f}) ===")
    all_values = {}
    all_values.update({f"raw.{k}": v for k, v in raw_fields.items() if isinstance(v, (int, float))})
    all_values.update({f"candidate.{k}": v for k, v in candidates.items()})
    
    for key, value in sorted(all_values.items(), key=lambda x: abs(x[1] - ui_balance_target)):
        diff = abs(value - ui_balance_target)
        diff_pct = (diff / ui_balance_target * 100) if ui_balance_target > 0 else 0
        if diff < 100:  # Within $100
            print(f"  {key}: ${value:,.2f} (diff: ${diff:,.2f}, {diff_pct:.2f}%)")
else:
    print("Reconcile data not present. Enable PORTFOLIO_RECONCILE_DEBUG=1 or use header X-Portfolio-Reconcile-Debug: 1")

