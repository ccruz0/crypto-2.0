#!/usr/bin/env python3
"""
CLI script to fetch and display portfolio reconcile evidence from /api/dashboard/state.

Usage:
    python3 fetch_reconcile_evidence.py [--api-base-url URL]

Exits with non-zero code if portfolio_value_source is derived (not exchange-reported).
"""

import sys
import json
import argparse
import requests
import os
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


def fetch_dashboard_state(api_base_url: str = "http://localhost:8002") -> Dict[str, Any]:
    """Fetch dashboard state from API."""
    url = f"{api_base_url}/api/dashboard/state"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"❌ Error fetching dashboard state: {e}", file=sys.stderr)
        sys.exit(1)


def fetch_reconcile_diagnostics(api_base_url: str = "http://localhost:8002") -> Optional[Dict[str, Any]]:
    """Fetch reconcile diagnostics from API (if available)."""
    url = f"{api_base_url}/api/diagnostics/portfolio/reconcile"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException:
        # Endpoint may not be available (gated by ENVIRONMENT or PORTFOLIO_DEBUG)
        return None


def save_json(data: Dict[str, Any], output_file: str):
    """Save data to JSON file."""
    try:
        with open(output_file, "w") as f:
            json.dump(data, f, indent=2)
        print(f"✅ Saved to: {output_file}")
    except Exception as e:
        print(f"⚠️  Warning: Could not save to {output_file}: {e}", file=sys.stderr)


def generate_summary(portfolio: Dict[str, Any], diagnostics: Optional[Dict[str, Any]] = None) -> str:
    """Generate human-readable summary text."""
    lines = []
    lines.append("=" * 80)
    lines.append("PORTFOLIO RECONCILE EVIDENCE")
    lines.append("=" * 80)
    lines.append("")
    
    total_value_usd = portfolio.get("total_value_usd", 0)
    portfolio_value_source = portfolio.get("portfolio_value_source", "MISSING")
    
    lines.append(f"📊 Total Value USD: ${total_value_usd:,.2f}")
    lines.append(f"📋 Portfolio Value Source: {portfolio_value_source}")
    lines.append("")
    
    reconcile = portfolio.get("reconcile", {})
    if not reconcile:
        lines.append("⚠️  No reconcile data found (PORTFOLIO_RECONCILE_DEBUG may not be enabled)")
        return "\n".join(lines)
    
    chosen = reconcile.get("chosen", {})
    if chosen:
        lines.append("✅ Chosen Field:")
        lines.append(f"   Field Path: {chosen.get('field_path', 'N/A')}")
        lines.append(f"   Value: ${chosen.get('value', 0):,.2f}")
        lines.append(f"   Priority: {chosen.get('priority', 'N/A')}")
        lines.append(f"   Source Key: {chosen.get('source_key', 'N/A')}")
        if "error" in chosen:
            lines.append(f"   ⚠️  Error: {chosen['error']}")
        lines.append("")
    
    candidates = reconcile.get("candidates", {})
    if candidates:
        lines.append(f"📋 Candidates ({len(candidates)}):")
        for key, value in candidates.items():
            lines.append(f"   {key}: ${value:,.2f}")
        lines.append("")
    
    raw_fields = reconcile.get("raw_fields", {})
    if raw_fields:
        # Filter and sort by value (descending)
        filtered_fields = {
            k: v for k, v in raw_fields.items()
            if any(term in k.lower() for term in ["wallet", "balance", "equity", "haircut", "total", "net", "margin"])
        }
        
        # Sort by value descending
        sorted_fields = sorted(filtered_fields.items(), key=lambda x: abs(x[1]) if isinstance(x[1], (int, float)) else 0, reverse=True)
        
        lines.append(f"📋 Top 30 Raw Fields (filtered):")
        for i, (field_path, value) in enumerate(sorted_fields[:30], 1):
            if isinstance(value, (int, float)):
                lines.append(f"   {i:2d}. {field_path}: ${value:,.2f}")
            else:
                lines.append(f"   {i:2d}. {field_path}: {value}")
        lines.append("")
    
    # Check if source is derived
    is_derived = portfolio_value_source.startswith("derived:")
    if is_derived:
        lines.append("❌ WARNING: Portfolio value source is DERIVED (not exchange-reported)")
        lines.append("   This may not match Crypto.com UI 'Wallet Balance (after haircut)'")
    else:
        lines.append("✅ Portfolio value source is EXCHANGE-REPORTED")
    
    return "\n".join(lines)


def print_reconcile_summary(portfolio: Dict[str, Any], diagnostics: Optional[Dict[str, Any]] = None) -> bool:
    """Print reconcile evidence summary and return True if exchange-reported."""
    summary = generate_summary(portfolio, diagnostics)
    print("\n" + summary)
    
    portfolio_value_source = portfolio.get("portfolio_value_source", "MISSING")
    is_derived = portfolio_value_source.startswith("derived:")
    return not is_derived


def main():
    parser = argparse.ArgumentParser(description="Fetch and display portfolio reconcile evidence")
    parser.add_argument(
        "--api-base-url",
        default="http://localhost:8002",
        help="API base URL (default: http://localhost:8002)"
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory (default: evidence/portfolio_reconcile/<timestamp>)"
    )
    args = parser.parse_args()
    
    # Create timestamped output directory
    if args.output_dir:
        output_dir = Path(args.output_dir)
    else:
        timestamp = datetime.utcnow().strftime("%Y-%m-%dT%H-%M-%SZ")
        output_dir = Path(__file__).parent / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Output directory: {output_dir}")
    
    # Fetch dashboard state
    print(f"🔍 Fetching dashboard state from: {args.api_base_url}/api/dashboard/state")
    data = fetch_dashboard_state(args.api_base_url)
    save_json(data, output_dir / "dashboard_state.json")
    
    # Fetch diagnostics (if available)
    print(f"🔍 Fetching diagnostics from: {args.api_base_url}/api/diagnostics/portfolio/reconcile")
    diagnostics = fetch_reconcile_diagnostics(args.api_base_url)
    if diagnostics:
        save_json(diagnostics, output_dir / "reconcile_diagnostics.json")
        print("✅ Diagnostics endpoint available")
    else:
        print("⚠️  Diagnostics endpoint not available (may require ENVIRONMENT=local or PORTFOLIO_DEBUG=1)")
    
    # Extract portfolio data
    portfolio = data.get("portfolio", {})
    if not portfolio:
        print("❌ No portfolio data in response", file=sys.stderr)
        sys.exit(1)
    
    # Generate and save summary
    summary_text = generate_summary(portfolio, diagnostics)
    with open(output_dir / "summary.txt", "w") as f:
        f.write(summary_text)
    
    # Print summary
    is_exchange = print_reconcile_summary(portfolio, diagnostics)
    
    # Exit with non-zero if derived
    if not is_exchange:
        print(f"\n❌ FAIL: Portfolio value source is derived, not exchange-reported")
        print(f"📁 Evidence saved to: {output_dir}")
        sys.exit(1)
    else:
        print(f"\n✅ PASS: Portfolio value source is exchange-reported")
        print(f"📁 Evidence saved to: {output_dir}")
        sys.exit(0)


if __name__ == "__main__":
    main()

