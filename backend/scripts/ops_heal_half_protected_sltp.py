#!/usr/bin/env python3
"""
Ops: repair SL-only (half-protected) parents via ensure_missing_protection.

Uses the same hourly path as scheduler (SLTP_HALF_PROTECTED_HEAL_ENABLED).
Does not invent protection for fully naked lots unless SLTP_HEALING_ENABLED
is also on (default OFF).

  docker exec <backend> python3 /repo/backend/scripts/ops_heal_half_protected_sltp.py
  docker exec <backend> python3 /repo/backend/scripts/ops_heal_half_protected_sltp.py --live
"""
from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import SessionLocal
from app.services.sl_tp_checker import sl_tp_checker_service


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Heal half-protected (SL-only) parents via ensure_missing_protection"
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Allow exchange writes (sets LIVE_TRADING=true for this process)",
    )
    args = parser.parse_args()

    # ensure_missing_protection uses LIVE_TRADING to choose dry_run.
    if args.live:
        os.environ["LIVE_TRADING"] = "true"
    else:
        os.environ["LIVE_TRADING"] = "false"

    db = SessionLocal()
    try:
        result = sl_tp_checker_service.ensure_missing_protection(db)
        summary = {
            "dry_run": not args.live,
            "half_protected_heal_only": result.get("half_protected_heal_only"),
            "healing_disabled": result.get("healing_disabled"),
            "created_n": len(result.get("created") or []),
            "failed_n": len(result.get("failed") or []),
            "skipped_n": len(result.get("skipped") or []),
            "still_missing_n": len(result.get("still_missing") or []),
            "created": (result.get("created") or [])[:40],
            "failed": (result.get("failed") or [])[:40],
            "skipped": (result.get("skipped") or [])[:40],
        }
        print(json.dumps(summary, default=str, indent=2))
        if result.get("error"):
            print(f"ERROR {result['error']}", file=sys.stderr)
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
