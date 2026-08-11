#!/usr/bin/env python3
"""
Cancel ghost/orphan protection legs flagged by dashboard Expected TP banner.

Uses ``app.services.ghost_protection`` (same rules as Monitoring Clean button):
  - wrong_side_cover_on_long  (BUY SL/TP while wallet > 0)
  - wrong_side_cover_on_short (SELL SL/TP while wallet < 0)
  - qty_exceeds_wallet / no_wallet

Default bases match the 2026-08-11 banner: ALGO×5, SUI×5, APT×4, AAVE×2.

  docker exec <backend> python3 /repo/backend/scripts/cancel_ghost_protection_alerts.py
  docker exec <backend> python3 /repo/backend/scripts/cancel_ghost_protection_alerts.py --live
  docker exec <backend> python3 /repo/backend/scripts/cancel_ghost_protection_alerts.py --live --bases ALGO,SUI
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import create_db_session
from app.services.ghost_protection import clean_ghost_protection_alerts

DEFAULT_BASES = ("ALGO", "SUI", "APT", "AAVE")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Cancel ghost/orphan SL/TP legs vs wallet (dashboard banner)"
    )
    parser.add_argument("--live", action="store_true", help="Cancel on exchange")
    parser.add_argument(
        "--bases",
        default=",".join(DEFAULT_BASES),
        help=f"Comma-separated base currencies (default {','.join(DEFAULT_BASES)})",
    )
    parser.add_argument(
        "--all-bases",
        action="store_true",
        help="Cancel ghosts for every base (ignore --bases)",
    )
    args = parser.parse_args()

    bases = None
    if not args.all_bases:
        bases = [b.strip().upper() for b in args.bases.split(",") if b.strip()]

    db = create_db_session()
    try:
        result = clean_ghost_protection_alerts(
            db,
            dry_run=not args.live,
            bases=bases,
        )
        print(
            f"mode={'LIVE' if args.live else 'DRY-RUN'} "
            f"ghost_alerts={result.get('count', 0)} "
            f"bases={sorted(bases) if bases else 'ALL'}"
        )
        if not result.get("count"):
            print("OK no matching ghost/orphan protection legs")
            return 0

        by_base = result.get("by_base") or {}
        if by_base:
            print(
                "by_base="
                + ",".join(f"{k}x{v}" for k, v in sorted(by_base.items()))
            )

        for entry in result.get("results") or []:
            print(
                f"{entry.get('status')} {entry.get('order_id')} "
                f"{entry.get('symbol')} {entry.get('side')} {entry.get('order_type')} "
                f"qty={entry.get('quantity')} wallet={entry.get('wallet_qty')} "
                f"reason={entry.get('reason')}"
                + (f" err={entry.get('error')}" if entry.get("error") else "")
            )

        print(
            f"=== SUMMARY cancelled={result.get('cancelled')} "
            f"failed={result.get('failed')} skipped={result.get('skipped')} "
            f"dry={result.get('dry_run')} ==="
        )
        if args.live and result.get("failed"):
            return 2
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
