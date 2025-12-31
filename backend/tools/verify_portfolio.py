#!/usr/bin/env python3
"""
CLI tool to verify portfolio match between dashboard and Crypto.com.

Usage:
    python -m tools.verify_portfolio
    python -m tools.verify_portfolio --endpoint http://localhost:8000
    python -m tools.verify_portfolio --endpoint https://dashboard.hilovivo.com --key <DIAGNOSTICS_API_KEY>
    python -m tools.verify_portfolio --full  # Use full endpoint instead of lite
"""

import sys
import os
import json
import argparse
from pathlib import Path

# Add parent directory to path to import app modules
sys.path.insert(0, str(Path(__file__).parent.parent))

def verify_portfolio(endpoint_url: str = None, api_key: str = None, use_full: bool = False):
    """Call the portfolio verification endpoint and display results."""
    import requests
    
    if endpoint_url is None:
        endpoint_url = os.getenv("API_URL", "http://localhost:8000")
    
    # Get API key from arg or env
    if api_key is None:
        api_key = os.getenv("DIAGNOSTICS_API_KEY")
    
    if not api_key:
        print("❌ Error: DIAGNOSTICS_API_KEY not set. Provide via --key flag or DIAGNOSTICS_API_KEY env var.")
        return 1
    
    # Use lite endpoint by default, full endpoint if --full flag
    endpoint_path = "/api/diagnostics/portfolio-verify" if use_full else "/api/diagnostics/portfolio-verify-lite"
    verify_url = f"{endpoint_url.rstrip('/')}{endpoint_path}"
    
    try:
        headers = {"X-Diagnostics-Key": api_key}
        response = requests.get(verify_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Display results
        print("=" * 70)
        print("Portfolio Verification Results")
        print("=" * 70)
        print(f"Dashboard NET:     ${data.get('dashboard_net_usd', 0):,.2f}")
        print(f"Crypto.com NET:    ${data.get('crypto_com_net_usd', 0):,.2f}")
        print(f"Difference:        ${data.get('diff_usd', 0):,.2f}")
        if 'diff_pct' in data:
            print(f"Difference %:      {data.get('diff_pct', 0):.4f}%")
        if 'tolerance_usd' in data:
            print(f"Tolerance:         ${data.get('tolerance_usd', 5.0):,.2f}")
        print(f"Status:            {'✅ PASS' if data.get('pass') else '❌ FAIL'}")
        print(f"Timestamp:         {data.get('timestamp', 'N/A')}")
        print("=" * 70)
        
        if not data.get('pass'):
            print("\n⚠️  Verification FAILED - Difference exceeds tolerance!")
            if 'tolerance_usd' in data:
                print(f"   Expected: ≤ ${data.get('tolerance_usd', 5.0):,.2f}")
            print(f"   Actual:   ${abs(data.get('diff_usd', 0)):,.2f}")
            return 1
        
        return 0
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Error calling verification endpoint: {e}")
        if hasattr(e, 'response') and e.response is not None:
            if e.response.status_code == 404:
                print("   Hint: Endpoint not found. Check ENABLE_DIAGNOSTICS_ENDPOINTS=1 and DIAGNOSTICS_API_KEY")
            else:
                print(f"   Response: {e.response.text}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        return 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Verify portfolio match between dashboard and Crypto.com")
    parser.add_argument(
        "--endpoint",
        type=str,
        default=None,
        help="API endpoint URL (default: http://localhost:8000 or API_URL env var)"
    )
    parser.add_argument(
        "--key",
        type=str,
        default=None,
        help="Diagnostics API key (default: DIAGNOSTICS_API_KEY env var)"
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Use full endpoint instead of lite (default: lite)"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw JSON instead of formatted text"
    )
    
    args = parser.parse_args()
    
    if args.json:
        import requests
        endpoint_url = args.endpoint or os.getenv("API_URL", "http://localhost:8000")
        api_key = args.key or os.getenv("DIAGNOSTICS_API_KEY")
        
        if not api_key:
            print(json.dumps({"error": "DIAGNOSTICS_API_KEY not set"}, indent=2))
            sys.exit(1)
        
        endpoint_path = "/api/diagnostics/portfolio-verify" if args.full else "/api/diagnostics/portfolio-verify-lite"
        verify_url = f"{endpoint_url.rstrip('/')}{endpoint_path}"
        try:
            headers = {"X-Diagnostics-Key": api_key}
            response = requests.get(verify_url, headers=headers, timeout=30)
            response.raise_for_status()
            print(json.dumps(response.json(), indent=2))
            sys.exit(0 if response.json().get('pass') else 1)
        except Exception as e:
            print(json.dumps({"error": str(e)}, indent=2))
            sys.exit(1)
    else:
        sys.exit(verify_portfolio(args.endpoint, args.key, args.full))

