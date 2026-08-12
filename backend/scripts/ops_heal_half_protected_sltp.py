#!/usr/bin/env python3
"""
Ops: repair SL-only (half-protected) parents via ensure_missing_protection.

Uses the same hourly path as scheduler (SLTP_HALF_PROTECTED_HEAL_ENABLED).
Does not invent protection for fully naked lots unless SLTP_HEALING_ENABLED
is also on (default OFF).

  docker exec <backend> python3 /repo/backend/scripts/ops_heal_half_protected_sltp.py
  docker exec <backend> python3 /repo/backend/scripts/ops_heal_half_protected_sltp.py --live
  docker exec <backend> python3 /repo/backend/scripts/ops_heal_half_protected_sltp.py --live --symbols ETH_USD,ETH_USDT
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Set

# Prefer image code (/app) over bind-mounted /repo, which often lags the deployed
# image and made ops dry-runs report healing_disabled after #451.
if os.path.isdir("/app/app"):
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.services.sl_tp_checker import sl_tp_checker_service
from app.services.sl_tp_protection import (
    is_sltp_half_protected_heal_enabled,
    is_sltp_healing_enabled,
)


def _git_sha() -> str:
    for path in ("/app/.git_sha", "/repo/.git/HEAD"):
        try:
            with open(path, encoding="utf-8") as fh:
                return fh.read().strip()[:40]
        except OSError:
            continue
    return "unknown"


def _append_multilot(
    symbol: str,
    multilot: Dict[str, Any],
    *,
    created: List[Dict],
    failed: List[Dict],
    skipped: List[Dict],
) -> None:
    for item in multilot.get("healed") or []:
        created.append(
            {
                "symbol": symbol,
                "sl_order_id": item.get("sl_order_id"),
                "tp_order_id": item.get("tp_order_id"),
                "parent_order_id": item.get("parent_order_id"),
                "source": "half_protected_heal",
            }
        )
    for item in multilot.get("failed") or []:
        failed.append({"symbol": symbol, **item})
    for item in multilot.get("skipped") or []:
        skipped.append({"symbol": symbol, **item})


def _heal_symbols_scoped(db, symbols: List[str]) -> Dict[str, Any]:
    """Heal only the given symbols (avoids full-book scan / SSM timeouts)."""
    want: Set[str] = {s.upper() for s in symbols}
    created: List[Dict] = []
    failed: List[Dict] = []
    skipped: List[Dict] = []
    seen: Set[str] = set()

    check = sl_tp_checker_service.check_positions_for_sl_tp(db)
    balance_by_symbol: Dict[str, float] = {}
    watchlist_by_symbol: Dict[str, Any] = {}
    for pos in check.get("positions_missing_sl_tp") or []:
        sym = (pos.get("symbol") or "").upper()
        if not sym:
            continue
        balance_by_symbol[sym] = float(pos.get("balance") or 0.0)
        if pos.get("watchlist_item") is not None:
            watchlist_by_symbol[sym] = pos.get("watchlist_item")

    # Always attempt requested symbols (balance lookup above; parent side from order).
    targets = sorted(want)

    for symbol in targets:
        if symbol in seen:
            continue
        seen.add(symbol)
        payload = {
            "symbol": symbol,
            "balance": balance_by_symbol.get(symbol, 0.0),
            "watchlist_item": watchlist_by_symbol.get(symbol),
        }
        try:
            multilot = sl_tp_checker_service._ensure_multilot_tp_heal(db, payload)
        except Exception as exc:  # noqa: BLE001 - ops summary must continue
            failed.append({"symbol": symbol, "error": f"half_protected_heal: {exc}"})
            continue
        _append_multilot(symbol, multilot, created=created, failed=failed, skipped=skipped)

    still_missing = [
        p
        for p in (sl_tp_checker_service.check_positions_for_sl_tp(db).get("positions_missing_sl_tp") or [])
        if (p.get("symbol") or "").upper() in want
    ]
    return {
        "created": created,
        "failed": failed,
        "skipped": skipped,
        "still_missing": still_missing,
        "healing_disabled": False,
        "half_protected_heal_only": True,
        "symbols_filter": sorted(want),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Heal half-protected (SL-only) parents via ensure_missing_protection"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow exchange writes (sets LIVE_TRADING=true for this process)",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Optional comma-separated symbols (e.g. ETH_USD,ETH_USDT). Empty = full book.",
    )
    args = parser.parse_args()

    # ensure_missing_protection uses LIVE_TRADING to choose dry_run.
    if args.live:
        os.environ["LIVE_TRADING"] = "true"
    else:
        os.environ["LIVE_TRADING"] = "false"

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()]

    db = SessionLocal()
    try:
        if symbols:
            if not is_sltp_half_protected_heal_enabled() and not is_sltp_healing_enabled():
                result = {
                    "created": [],
                    "failed": [],
                    "skipped": [],
                    "still_missing": [],
                    "healing_disabled": True,
                    "half_protected_heal_only": None,
                    "symbols_filter": symbols,
                }
            else:
                result = _heal_symbols_scoped(db, symbols)
        else:
            result = sl_tp_checker_service.ensure_missing_protection(db)

        summary = {
            "dry_run": not args.live,
            "git_sha": _git_sha(),
            "full_healing_enabled": is_sltp_healing_enabled(),
            "half_protected_heal_enabled": is_sltp_half_protected_heal_enabled(),
            "half_protected_heal_only": result.get("half_protected_heal_only"),
            "healing_disabled": result.get("healing_disabled"),
            "symbols_filter": result.get("symbols_filter") or symbols or None,
            "created_n": len(result.get("created") or []),
            "failed_n": len(result.get("failed") or []),
            "skipped_n": len(result.get("skipped") or []),
            "still_missing_n": len(result.get("still_missing") or []),
            "created": (result.get("created") or [])[:40],
            "failed": (result.get("failed") or [])[:40],
            "skipped": (result.get("skipped") or [])[:40],
        }
        print(json.dumps(summary, default=str, indent=2), flush=True)
        if result.get("error"):
            print(f"ERROR {result['error']}", file=sys.stderr)
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
