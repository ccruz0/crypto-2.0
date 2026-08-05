#!/usr/bin/env python3
"""Build trade_outcomes round-trip labels (Phase 1a — LAB-safe).

Joins telegram_messages ← order_intents ← exchange_orders entry ← SL/TP children.
Drops incomplete joins and prints join coverage. Does NOT promote Auto ML models.

Usage:
  # Demo / fixtures (no DB)
  python3 scripts/build_trade_outcomes.py --demo

  # Read DB, write JSON only (no table writes)
  python3 scripts/build_trade_outcomes.py --database-url "$DATABASE_URL" --days 90 --dry-run

  # Upsert into trade_outcomes (after migration applied on LAB)
  python3 scripts/build_trade_outcomes.py --database-url "$DATABASE_URL" --days 90 --write-db
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BACKEND = _REPO_ROOT / "backend"
for p in (_BACKEND,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from app.services.trade_outcome_builder import (  # noqa: E402
    build_outcomes_from_fixtures,
    coverage_report_dict,
    load_rows_from_db,
    upsert_outcomes,
)


def _demo_fixtures() -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[Any, dict[str, Any]],
]:
    base = datetime(2026, 7, 1, 12, 0, tzinfo=timezone.utc)
    intents = [
        {
            "id": 1,
            "signal_id": 101,
            "symbol": "BTC_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": "entry-win",
        },
        {
            "id": 2,
            "signal_id": 102,
            "symbol": "ETH_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": "entry-loss",
        },
        {
            "id": 3,
            "signal_id": 103,
            "symbol": "SOL_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": "entry-open",
        },
        {
            "id": 4,
            "symbol": "DOT_USD",
            "side": "BUY",
            "status": "ORDER_PLACED",
            "order_id": None,  # dropped
        },
    ]
    entries = {
        "entry-win": {
            "exchange_order_id": "entry-win",
            "symbol": "BTC_USD",
            "side": "BUY",
            "order_type": "LIMIT",
            "status": "FILLED",
            "avg_price": 100.0,
            "quantity": 1.0,
            "exchange_create_time": base,
        },
        "entry-loss": {
            "exchange_order_id": "entry-loss",
            "symbol": "ETH_USD",
            "side": "BUY",
            "order_type": "LIMIT",
            "status": "FILLED",
            "avg_price": 50.0,
            "quantity": 2.0,
            "exchange_create_time": base,
        },
        "entry-open": {
            "exchange_order_id": "entry-open",
            "symbol": "SOL_USD",
            "side": "BUY",
            "order_type": "LIMIT",
            "status": "FILLED",
            "avg_price": 10.0,
            "quantity": 5.0,
            "exchange_create_time": base,
        },
    }
    children = {
        "entry-win": [
            {
                "exchange_order_id": "tp-win",
                "parent_order_id": "entry-win",
                "order_role": "TAKE_PROFIT",
                "order_type": "TAKE_PROFIT_LIMIT",
                "status": "FILLED",
                "avg_price": 110.0,
                "quantity": 1.0,
                "exchange_update_time": base + timedelta(hours=2),
            },
            {
                "exchange_order_id": "sl-win-cancel",
                "parent_order_id": "entry-win",
                "order_role": "STOP_LOSS",
                "order_type": "STOP_LIMIT",
                "status": "CANCELLED",
                "avg_price": 90.0,
                "quantity": 1.0,
                "exchange_update_time": base + timedelta(hours=2),
            },
        ],
        "entry-loss": [
            {
                "exchange_order_id": "sl-loss",
                "parent_order_id": "entry-loss",
                "order_role": "STOP_LOSS",
                "order_type": "STOP_LIMIT",
                "status": "FILLED",
                "avg_price": 45.0,
                "quantity": 2.0,
                "exchange_update_time": base + timedelta(hours=1),
            },
        ],
        "entry-open": [
            {
                "exchange_order_id": "tp-open",
                "parent_order_id": "entry-open",
                "order_role": "TAKE_PROFIT",
                "order_type": "TAKE_PROFIT_LIMIT",
                "status": "ACTIVE",
                "price": 12.0,
                "quantity": 5.0,
            },
        ],
    }
    alerts = {
        101: {"id": 101, "symbol": "BTC_USD"},
        102: {"id": 102, "symbol": "ETH_USD"},
        103: {"id": 103, "symbol": "SOL_USD"},
    }
    return intents, entries, children, alerts


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build trade_outcomes round-trip labels (Phase 1a)")
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--demo", action="store_true", help="Built-in fixtures (no DB)")
    src.add_argument(
        "--database-url",
        default=None,
        help="Postgres URL (or set DATABASE_URL). Never logged.",
    )
    src.add_argument(
        "--fixtures-json",
        type=Path,
        help="JSON with intents, entries_by_id, children_by_parent, optional alerts_by_id",
    )
    p.add_argument("--days", type=int, default=90, help="Lookback for intents (DB mode)")
    p.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "docs" / "analysis" / "trade-outcomes-coverage.json",
        help="Coverage / sample report path",
    )
    p.add_argument(
        "--write-db",
        action="store_true",
        help="Upsert COMPLETE rows into trade_outcomes (requires migration)",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Never write DB (default unless --write-db)",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    # Prefer explicit --database-url; allow env only when flag chosen empty via nargs? Keep simple:
    db_url = args.database_url
    if db_url is None and not args.demo and args.fixtures_json is None:
        db_url = os.environ.get("DATABASE_URL")

    if args.demo:
        intents, entries, children, alerts = _demo_fixtures()
        source = "demo"
    elif args.fixtures_json:
        data = json.loads(args.fixtures_json.read_text(encoding="utf-8"))
        intents = data["intents"]
        entries = data["entries_by_id"]
        children = data["children_by_parent"]
        alerts = {int(k) if str(k).isdigit() else k: v for k, v in (data.get("alerts_by_id") or {}).items()}
        source = f"json:{args.fixtures_json}"
    else:
        url = db_url or os.environ.get("DATABASE_URL")
        if not url:
            print("Provide --demo, --fixtures-json, or --database-url / DATABASE_URL", file=sys.stderr)
            return 2
        intents, entries, children, alerts = load_rows_from_db(url, days=args.days)
        source = "database"

    rows, stats = build_outcomes_from_fixtures(
        intents=intents,
        entries_by_id=entries,
        children_by_parent=children,
        alerts_by_id=alerts,
    )

    report = coverage_report_dict(rows, stats)
    report["source"] = source
    # Cap sample rows in report for readability
    report["sample_rows"] = [
        {
            k: (v.isoformat() if isinstance(v, datetime) else v)
            for k, v in r.items()
            if k != "meta_json"
        }
        for r in rows[:20]
    ]

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report["coverage"], indent=2))
    print(f"Wrote coverage → {args.out}", file=sys.stderr)

    write_db = bool(args.write_db) and not args.dry_run and not args.demo
    if args.write_db and args.demo:
        print("Refusing --write-db with --demo (use --fixtures-json + DB URL if needed)", file=sys.stderr)
        return 0
    if write_db:
        url = db_url or os.environ.get("DATABASE_URL")
        if not url:
            print("--write-db requires --database-url / DATABASE_URL", file=sys.stderr)
            return 2
        n = upsert_outcomes(url, rows)
        print(json.dumps({"upserted": n}), file=sys.stderr)
    elif args.write_db and args.dry_run:
        print(json.dumps({"note": "dry_run_skipped_write", "would_upsert": len(rows)}), file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
