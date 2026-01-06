#!/usr/bin/env python3
"""
Extract portfolio evidence from dashboard_state.json
Safe - only prints numeric values and field paths (no secrets)
"""
import json
import sys
from pathlib import Path

def filter_raw_fields(raw_fields, keywords):
    """Filter raw_fields by keywords (case-insensitive)"""
    if not raw_fields or not isinstance(raw_fields, dict):
        return {}
    
    filtered = {}
    keywords_lower = [k.lower() for k in keywords]
    
    for key, value in raw_fields.items():
        key_lower = key.lower()
        if any(kw in key_lower for kw in keywords_lower):
            # Only include numeric values (safe)
            if isinstance(value, (int, float)):
                filtered[key] = value
            elif isinstance(value, str) and value.replace('.', '').replace('-', '').isdigit():
                try:
                    filtered[key] = float(value)
                except ValueError:
                    pass
    
    return dict(sorted(filtered.items()))

def main():
    if len(sys.argv) < 2:
        print("Usage: extract_portfolio.py <dashboard_state.json> [output_dir]", file=sys.stderr)
        sys.exit(1)
    
    json_path = Path(sys.argv[1])
    output_dir = Path(sys.argv[2]) if len(sys.argv) > 2 else json_path.parent
    
    if not json_path.exists():
        print(f"Error: {json_path} not found", file=sys.stderr)
        sys.exit(1)
    
    with open(json_path, 'r') as f:
        data = json.load(f)
    
    portfolio = data.get('portfolio', {})
    
    if not portfolio:
        print("Error: No portfolio data found", file=sys.stderr)
        sys.exit(1)
    
    # Extract key fields
    total_value_usd = portfolio.get('total_value_usd')
    portfolio_value_source = portfolio.get('portfolio_value_source')
    reconcile = portfolio.get('reconcile', {})
    
    # Build text report
    report_lines = []
    report_lines.append("=" * 80)
    report_lines.append("PORTFOLIO EVIDENCE EXTRACT")
    report_lines.append("=" * 80)
    report_lines.append("")
    
    report_lines.append(f"total_value_usd: {total_value_usd}")
    report_lines.append(f"portfolio_value_source: {portfolio_value_source}")
    report_lines.append("")
    
    if reconcile:
        report_lines.append("RECONCILE DATA:")
        report_lines.append("-" * 80)
        
        chosen = reconcile.get('chosen', {})
        if chosen:
            report_lines.append(f"chosen.value: {chosen.get('value')}")
            report_lines.append(f"chosen.source_key: {chosen.get('source_key')}")
            report_lines.append(f"chosen.field_path: {chosen.get('field_path')}")
            report_lines.append(f"chosen.priority: {chosen.get('priority')}")
            if 'error' in chosen:
                report_lines.append(f"chosen.error: {chosen.get('error')}")
            report_lines.append("")
        
        candidates = reconcile.get('candidates', {})
        if candidates:
            report_lines.append("candidates:")
            for key, value in sorted(candidates.items()):
                if isinstance(value, (int, float)):
                    report_lines.append(f"  {key}: ${value:,.2f}")
                else:
                    report_lines.append(f"  {key}: {value}")
            report_lines.append("")
        
        raw_fields = reconcile.get('raw_fields', {})
        if raw_fields:
            # Filter raw_fields by keywords
            keywords = ["wallet", "balance", "equity", "haircut", "total", "net", "margin"]
            filtered = filter_raw_fields(raw_fields, keywords)
            
            report_lines.append(f"raw_fields (filtered by: {', '.join(keywords)}):")
            report_lines.append(f"  Total fields found: {len(raw_fields)}")
            report_lines.append(f"  Filtered fields: {len(filtered)}")
            report_lines.append("")
            
            if filtered:
                report_lines.append("Filtered raw_fields (top 20):")
                for i, (key, value) in enumerate(list(filtered.items())[:20], 1):
                    if isinstance(value, (int, float)):
                        report_lines.append(f"  {i:2d}. {key}: ${value:,.2f}")
                    else:
                        report_lines.append(f"  {i:2d}. {key}: {value}")
            else:
                report_lines.append("  (No fields matched filter keywords)")
            report_lines.append("")
    else:
        report_lines.append("RECONCILE DATA: Not present (PORTFOLIO_RECONCILE_DEBUG=1 may not be enabled)")
        report_lines.append("")
    
    report_lines.append("=" * 80)
    
    # Write text report
    report_path = output_dir / "portfolio_extract.txt"
    with open(report_path, 'w') as f:
        f.write('\n'.join(report_lines))
    
    print(f"✅ Text report saved to: {report_path}")
    
    # Write portfolio-only JSON
    portfolio_json_path = output_dir / "portfolio_only.json"
    with open(portfolio_json_path, 'w') as f:
        json.dump(portfolio, f, indent=2)
    
    print(f"✅ Portfolio JSON saved to: {portfolio_json_path}")
    
    # Print summary to stdout
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"total_value_usd: {total_value_usd}")
    print(f"portfolio_value_source: {portfolio_value_source}")
    if reconcile and reconcile.get('chosen'):
        chosen = reconcile['chosen']
        print(f"reconcile.chosen.field_path: {chosen.get('field_path')}")
        print(f"reconcile.chosen.value: {chosen.get('value')}")
        print(f"reconcile.chosen.priority: {chosen.get('priority')}")
    else:
        print("reconcile.chosen: Not available (PORTFOLIO_RECONCILE_DEBUG=1 may not be enabled)")
    
    if reconcile and reconcile.get('raw_fields'):
        filtered = filter_raw_fields(reconcile['raw_fields'], 
                                    ["wallet", "balance", "equity", "haircut", "total", "net", "margin"])
        print(f"\nFiltered raw_fields (top 10):")
        for key, value in list(filtered.items())[:10]:
            if isinstance(value, (int, float)):
                print(f"  {key}: ${value:,.2f}")
            else:
                print(f"  {key}: {value}")

if __name__ == '__main__':
    main()

