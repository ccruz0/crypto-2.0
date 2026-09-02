#!/usr/bin/env python3
"""Build trade_outcomes round-trip labels (Phase 1a — LAB-safe).

Joins telegram_messages ← order_intents ← exchange_orders entry ← SL/TP children
(or orphan opposite MARKET/LIMIT flatten). Excludes dry-run synthetic order ids
and STUB-CLOSED-* exits from COMPLETE train rows. Drops incomplete joins and
prints join coverage. Does NOT promote Auto ML models.

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


def trade_outcomes_max_updated_age_hours(database_url: str) -> float:
    """Hours since max(trade_outcomes.updated_at); 99999.0 when table empty."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise RuntimeError("sqlalchemy required for --skip-if-fresh-hours") from e

    engine = create_engine(database_url)
    sql = text(
        """
        SELECT COALESCE(
          EXTRACT(EPOCH FROM (NOW() AT TIME ZONE 'UTC' - max(updated_at))) / 3600.0,
          99999.0
        )
        FROM trade_outcomes
        """
    )
    sql_sqlite = text(
        """
        SELECT COALESCE(
          (julianday('now') - julianday(max(updated_at))) * 24.0,
          99999.0
        )
        FROM trade_outcomes
        """
    )
    q = sql_sqlite if engine.dialect.name == "sqlite" else sql
    with engine.connect() as conn:
        row = conn.execute(q).fetchone()
    if row is None or row[0] is None:
        return 99999.0
    return float(row[0])


def _demo_fixtures() -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
    dict[Any, dict[str, Any]],
    list[dict[str, Any]],
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
        {
            "id": 5,
            "signal_id": 105,
            "symbol": "AAVE_USD",
            "side": "SELL",
            "status": "ORDER_PLACED",
            "order_id": "entry-orphan",
        },
        {
            "id": 6,
            "symbol": "ETH_USDT",
            "side": "SELL",
            "status": "ORDER_PLACED",
            "order_id": "dry_market_1782920132",  # excluded from eligible
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
        "entry-orphan": {
            "exchange_order_id": "entry-orphan",
            "symbol": "AAVE_USD",
            "side": "SELL",
            "order_type": "LIMIT",
            "status": "FILLED",
            "avg_price": 200.0,
            "quantity": 1.5,
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
        "entry-orphan": [
            {
                "exchange_order_id": "sl-orphan-cancel",
                "parent_order_id": "entry-orphan",
                "order_role": "STOP_LOSS",
                "order_type": "STOP_LIMIT",
                "status": "CANCELLED",
                "price": 220.0,
                "quantity": 1.5,
            },
            {
                "exchange_order_id": "tp-orphan-cancel",
                "parent_order_id": "entry-orphan",
                "order_role": "TAKE_PROFIT",
                "order_type": "TAKE_PROFIT_LIMIT",
                "status": "CANCELLED",
                "price": 180.0,
                "quantity": 1.5,
            },
        ],
    }
    orphans = [
        {
            "exchange_order_id": "orphan-flatten-aave",
            "symbol": "AAVE_USD",
            "side": "BUY",
            "order_type": "MARKET",
            "status": "FILLED",
            "avg_price": 195.0,
            "quantity": 1.5,
            "parent_order_id": None,
            "exchange_update_time": base + timedelta(hours=6),
        },
    ]
    alerts = {
        101: {"id": 101, "symbol": "BTC_USD"},
        102: {"id": 102, "symbol": "ETH_USD"},
        103: {"id": 103, "symbol": "SOL_USD"},
        105: {"id": 105, "symbol": "AAVE_USD"},
    }
    return intents, entries, children, alerts, orphans


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
        help="JSON with intents, entries_by_id, children_by_parent, optional alerts_by_id / orphan_candidates",
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
    p.add_argument(
        "--skip-if-fresh-hours",
        type=float,
        default=None,
        metavar="HOURS",
        help=(
            "Skip rebuild when max(trade_outcomes.updated_at) is newer than HOURS "
            "(ops daily job refreshes updated_at even without new closes)"
        ),
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    # Prefer explicit --database-url; allow env only when flag chosen empty via nargs? Keep simple:
    db_url = args.database_url
    if db_url is None and not args.demo and args.fixtures_json is None:
        db_url = os.environ.get("DATABASE_URL")

    orphans: list[dict[str, Any]] = []
    if args.demo:
        intents, entries, children, alerts, orphans = _demo_fixtures()
        short_close_buys: list[dict[str, Any]] = []
        source = "demo"
    elif args.fixtures_json:
        data = json.loads(args.fixtures_json.read_text(encoding="utf-8"))
        intents = data["intents"]
        entries = data["entries_by_id"]
        children = data["children_by_parent"]
        alerts = {int(k) if str(k).isdigit() else k: v for k, v in (data.get("alerts_by_id") or {}).items()}
        orphans = list(data.get("orphan_candidates") or [])
        short_close_buys = list(data.get("short_close_buys") or [])
        source = f"json:{args.fixtures_json}"
    else:
        url = db_url or os.environ.get("DATABASE_URL")
        if not url:
            print("Provide --demo, --fixtures-json, or --database-url / DATABASE_URL", file=sys.stderr)
            return 2
        if args.skip_if_fresh_hours is not None:
            age_h = trade_outcomes_max_updated_age_hours(url)
            threshold = float(args.skip_if_fresh_hours)
            if age_h <= threshold:
                skip_payload = {
                    "skipped": True,
                    "reason": "trade_outcomes_fresh",
                    "max_updated_at_age_hours": round(age_h, 3),
                    "threshold_hours": threshold,
                }
                print(json.dumps(skip_payload), file=sys.stderr)
                print(json.dumps(skip_payload))
                return 0
            print(
                json.dumps(
                    {
                        "skipped": False,
                        "reason": "trade_outcomes_stale",
                        "max_updated_at_age_hours": round(age_h, 3),
                        "threshold_hours": threshold,
                    }
                ),
                file=sys.stderr,
            )
        intents, entries, children, alerts, orphans, short_close_buys = load_rows_from_db(url, days=args.days)
        source = "database"

    rows, stats = build_outcomes_from_fixtures(
        intents=intents,
        entries_by_id=entries,
        children_by_parent=children,
        alerts_by_id=alerts,
        orphan_candidates=orphans,
        short_close_buys=short_close_buys,
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
