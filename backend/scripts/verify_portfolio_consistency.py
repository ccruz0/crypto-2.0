#!/usr/bin/env python3
"""
Portfolio consistency verification: calls GET /api/dashboard/state in-process
(TestClient) and via HTTP (curl path), then compares portfolio totals.

Use after a rebuild to confirm portfolio math and routing match. No secrets printed.

Usage:
  python scripts/verify_portfolio_consistency.py
  python scripts/verify_portfolio_consistency.py --live   # Force refresh before computing
  python scripts/verify_portfolio_consistency.py --json  # Machine-readable for CI/cron
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

# Ensure backend app is on path
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_BACKEND_DIR = os.path.dirname(_SCRIPT_DIR)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Float comparison tolerance (USD)
TOLERANCE = 0.01


def _get_git_sha() -> Optional[str]:
    """Return current git SHA if available (env or repo)."""
    sha = os.getenv("COMMIT_SHA") or os.getenv("GIT_SHA")
    if sha:
        return sha.strip()[:12]
    try:
        # Repo root is typically backend/.. or cwd
        for root in (_BACKEND_DIR, os.path.dirname(_BACKEND_DIR), "."):
            p = os.path.join(root, ".git")
            if os.path.isdir(p):
                result = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    cwd=root,
                    capture_output=True,
                    text=True,
                    timeout=2,
                )
                if result.returncode == 0 and result.stdout:
                    return result.stdout.strip()[:12]
                break
    except Exception:
        pass
    return None


def _extract_portfolio_summary(state: Dict[str, Any]) -> Dict[str, Any]:
    """Extract the same portfolio fields the dashboard exposes."""
    portfolio = state.get("portfolio") or {}
    assets = portfolio.get("assets") or []
    return {
        "total_collateral_usd": float(portfolio.get("total_collateral_usd") or 0.0),
        "total_borrowed_usd": float(portfolio.get("total_borrowed_usd") or 0.0),
        "total_value_usd": float(portfolio.get("total_value_usd") or 0.0),
        "assets_count": len(assets),
        "source": portfolio.get("portfolio_value_source") or "unknown",
        "as_of": portfolio.get("as_of"),
    }


def _format_snapshot(as_of: Optional[str]) -> str:
    if as_of is None:
        return "N/A"
    return str(as_of)


def _print_block(title: str, p: Dict[str, Any]) -> None:
    print(title)
    print(f"Collateral: ${p['total_collateral_usd']:,.2f}")
    print(f"Borrowed:   ${p['total_borrowed_usd']:,.2f}")
    print(f"Net Value:  ${p['total_value_usd']:,.2f}")
    print(f"Assets:     {p['assets_count']}")
    print(f"Source:     {p['source']}")
    print(f"Snapshot:   {_format_snapshot(p['as_of'])}")
    print()


def _within_tolerance(a: float, b: float) -> bool:
    return abs(a - b) < TOLERANCE


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify portfolio in-process vs HTTP consistency")
    parser.add_argument(
        "--live",
        action="store_true",
        help="Force portfolio refresh (update cache + fetch and store snapshot) before computing",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("BACKEND_URL", "http://127.0.0.1:8002"),
        help="Base URL for API / curl path (default: BACKEND_URL or http://127.0.0.1:8002)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print a single JSON blob (match, internal, api, delta, timestamp) for CI/cron",
    )
    args = parser.parse_args()

    from app.database import create_db_session

    try:
        db = create_db_session()
    except RuntimeError as e:
        if args.json:
            print(json.dumps({"match": False, "error": str(e)}))
        else:
            print(f"ERROR: Database not available: {e}")
        return 1
    try:
        if args.live:
            if not args.json:
                print("Refreshing portfolio (--live)...")
            from app.services.portfolio_cache import update_portfolio_cache
            from app.services.portfolio_snapshot import fetch_live_portfolio_snapshot, store_portfolio_snapshot

            update_result = update_portfolio_cache(db)
            if not update_result.get("success") and not args.json:
                print(f"Warning: update_portfolio_cache failed: {update_result.get('error', 'unknown')}")
            try:
                snapshot = fetch_live_portfolio_snapshot(db)
                if snapshot and snapshot.get("assets") is not None:
                    store_portfolio_snapshot(db, snapshot)
            except Exception as e:
                if not args.json:
                    print(f"Warning: snapshot refresh failed: {e}")
            if not args.json:
                print()
    finally:
        db.close()

    # Internal = in-process route (same stack as production)
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    resp_internal = client.get("/api/dashboard/state")
    if resp_internal.status_code != 200:
        if args.json:
            out = {
                "match": False,
                "error": f"in_process_route returned {resp_internal.status_code}",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if _get_git_sha():
                out["git_sha"] = _get_git_sha()
            print(json.dumps(out))
        else:
            print("=== IN-PROCESS ROUTE (TestClient) ===")
            print(f"ERROR: GET /api/dashboard/state returned {resp_internal.status_code}")
            print(resp_internal.text[:500] if resp_internal.text else "")
        return 1

    state_internal = resp_internal.json()
    internal = _extract_portfolio_summary(state_internal)

    # External = curl path (real HTTP)
    try:
        import urllib.request

        url = f"{args.base_url.rstrip('/')}/api/dashboard/state"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=15) as resp:
            api_state = json.loads(resp.read().decode())
    except Exception as e:
        if args.json:
            out = {
                "match": False,
                "error": f"api_unreachable: {e!s}",
                "internal": {
                    "collateral": round(internal["total_collateral_usd"], 2),
                    "borrowed": round(internal["total_borrowed_usd"], 2),
                    "net": round(internal["total_value_usd"], 2),
                    "assets": internal["assets_count"],
                },
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
            if _get_git_sha():
                out["git_sha"] = _get_git_sha()
            print(json.dumps(out))
        else:
            print("=== IN-PROCESS ROUTE (TestClient) ===")
            _print_block("", internal)
            print("=== API (curl path) ===")
            print(f"ERROR: Could not fetch API: {e}")
            print()
            print("RESULT: SKIP (API unreachable; in-process values above)")
        return 1

    api = _extract_portfolio_summary(api_state)

    # If API returned error payload, force mismatch
    api_source = api_state.get("source")
    api_errors = api_state.get("errors") or []
    if api_source == "error":
        match = False
        if args.json:
            pass  # will build payload with match=False and detail below
        else:
            print("=== IN-PROCESS ROUTE (TestClient) ===")
            _print_block("", internal)
            print("=== API (curl path) ===")
            _print_block("", api)
            print("RESULT: MISMATCH (API returned source=error)")
            if api_errors:
                print("API errors:", api_errors)
            return 1
    else:
        match = (
            _within_tolerance(internal["total_collateral_usd"], api["total_collateral_usd"])
            and _within_tolerance(internal["total_borrowed_usd"], api["total_borrowed_usd"])
            and _within_tolerance(internal["total_value_usd"], api["total_value_usd"])
            and internal["assets_count"] == api["assets_count"]
        )

    # Build compact numeric dicts for --json
    internal_compact = {
        "collateral": round(internal["total_collateral_usd"], 2),
        "borrowed": round(internal["total_borrowed_usd"], 2),
        "net": round(internal["total_value_usd"], 2),
        "assets": internal["assets_count"],
    }
    api_compact = {
        "collateral": round(api["total_collateral_usd"], 2),
        "borrowed": round(api["total_borrowed_usd"], 2),
        "net": round(api["total_value_usd"], 2),
        "assets": api["assets_count"],
    }
    delta = {
        "collateral": round(internal["total_collateral_usd"] - api["total_collateral_usd"], 2),
        "borrowed": round(internal["total_borrowed_usd"] - api["total_borrowed_usd"], 2),
        "net": round(internal["total_value_usd"] - api["total_value_usd"], 2),
        "assets": internal["assets_count"] - api["assets_count"],
    }

    if args.json:
        out = {
            "match": match,
            "tolerance": TOLERANCE,
            "internal": internal_compact,
            "api": api_compact,
            "delta": delta,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        if api_source == "error":
            out["match"] = False
            out["api_source"] = api_source
            out["api_errors"] = api_errors
        sha = _get_git_sha()
        if sha:
            out["git_sha"] = sha
        print(json.dumps(out))
        return 0 if match else 1

    # Human output
    git_sha = _get_git_sha()
    if git_sha:
        print(f"Backend git SHA: {git_sha}")
        print()

    print("=== IN-PROCESS ROUTE (TestClient) ===")
    _print_block("", internal)
    print("=== API (curl path) ===")
    _print_block("", api)

    if match:
        print("RESULT: MATCH")
        return 0
    else:
        print("RESULT: MISMATCH")
        print("Deltas (in-process - API):")
        print(f"  total_collateral_usd: {delta['collateral']:+.2f}")
        print(f"  total_borrowed_usd:   {delta['borrowed']:+.2f}")
        print(f"  total_value_usd:     {delta['net']:+.2f}")
        print(f"  assets_count:        {delta['assets']:+d}")
        if internal["source"] != api["source"]:
            print(f"  source:               in_process={internal['source']!r}  api={api['source']!r}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
