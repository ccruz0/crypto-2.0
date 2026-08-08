#!/usr/bin/env python3
"""Build offline Auto ML training dataset from labeled alerts and/or trade outcomes.

Phase 0: alert-path labels (OHLCV forward: dir_acc_1h OR tp_before_sl).
Phase 1b: COMPLETE trade_outcomes labels (y=1 if pnl_usd > 0) joined to alert
          context features. Use --label-source hybrid to study executed fills
          *and* keep alert-path rows when no fill exists.

Does NOT mutate trading_config, enable live ML gate, or write secrets.

Usage:
  python3 scripts/build_auto_ml_dataset.py --demo
  python3 scripts/build_auto_ml_dataset.py --api-url https://dashboard.hilovivo.com --days 30
  python3 scripts/build_auto_ml_dataset.py --database-url "$DATABASE_URL" --days 90 \\
      --label-source hybrid
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from alert_quality_metrics import DEFAULT_DELTA  # noqa: E402
from auto_ml_features import (  # noqa: E402
    FEATURE_NAMES,
    FEATURE_VERSION,
    TRADE_OUTCOME_LABEL_DEF,
    attach_features_and_label,
    attach_features_from_trade_outcomes,
    merge_alert_and_trade_datasets,
)
from eval_alert_quality import (  # noqa: E402
    evaluate_alerts,
    load_alerts_from_api,
    load_alerts_from_db,
    load_alerts_from_json,
    normalize_alert,
)


ALERT_LABEL_DEF = "y=1 if dir_acc_1h OR tp_before_sl; else 0 when dir_acc_1h is False"
HYBRID_LABEL_DEF = (
    "prefer trade_outcomes COMPLETE (pnl_usd>0); else alert-path "
    "(dir_acc_1h OR tp_before_sl)"
)


def build_rich_demo_alerts() -> list[dict[str, Any]]:
    """Demo alerts with indicator context so feature extraction is non-trivial."""
    base = datetime.now(timezone.utc) - timedelta(hours=8)
    rows: list[dict[str, Any]] = []
    # Mix of would-be winners (fixture candles drift with side) and varied features
    specs = [
        ("BTC_USDT", "BUY", 65000.0, 28.0, 64000.0, 60000.0, 64500.0, 1.4, 800.0, 90),
        ("ETH_USDT", "BUY", 3200.0, 25.0, 3150.0, 3000.0, 3180.0, 1.2, 40.0, 80),
        ("SOL_USDT", "SELL", 140.0, 75.0, 142.0, 150.0, 141.0, 0.9, 3.0, 70),
        ("AAVE_USD", "BUY", 95.8, 32.0, 94.0, 90.0, 95.0, 1.1, 2.5, 85),
        ("DOT_USDT", "SELL", 6.5, 72.0, 6.6, 7.0, 6.55, 1.0, 0.15, 60),
        ("LINK_USDT", "BUY", 14.0, 29.0, 13.8, 13.0, 13.9, 1.5, 0.4, 95),
        ("AVAX_USDT", "BUY", 35.0, 35.0, 34.5, 32.0, 34.8, 0.8, 1.0, 55),
        ("ATOM_USDT", "SELL", 8.0, 78.0, 8.1, 8.5, 8.05, 1.3, 0.2, 65),
    ]
    for i, (sym, side, px, rsi, ma50, ma200, ema10, vol, atr, idx) in enumerate(specs):
        emoji = "🟢" if side == "BUY" else "🔴"
        ts = (base + timedelta(minutes=15 * i)).isoformat()
        # Alternate adverse fixture paths so the demo has both y=0 and y=1.
        adverse = i % 2 == 1
        rows.append(
            {
                "id": i + 1,
                "symbol": sym,
                "message": (
                    f"{emoji} {side} SIGNAL DETECTED\n"
                    f"📈 Symbol: {sym}\n"
                    f"💵 Price: ${px:.4f}\n"
                    f"🎯 Strategy: Auto\n"
                    f"⚖️ Approach: Conservative"
                ),
                "blocked": False,
                "timestamp": ts,
                "context_json": {
                    "entry_price": px,
                    "price": px,
                    "rsi": rsi,
                    "ma50": ma50,
                    "ma200": ma200,
                    "ema10": ema10,
                    "volume_ratio": vol,
                    "atr": atr,
                    "strategy_index": idx,
                    "strategy_type": "auto",
                    "risk_approach": "Learned",
                    "fixture_adverse": adverse,
                },
            }
        )
    return rows


def load_complete_outcomes_with_alerts(
    database_url: str, *, days: int, limit: int = 5000
) -> list[dict[str, Any]]:
    """COMPLETE trade_outcomes joined to telegram_messages.context_json (no secrets logged)."""
    try:
        from sqlalchemy import create_engine, text
    except ImportError as e:
        raise RuntimeError("sqlalchemy required for --label-source trade_outcomes/hybrid") from e

    engine = create_engine(database_url)
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    sql = text(
        """
        SELECT
          o.telegram_message_id,
          o.order_intent_id,
          o.entry_exchange_order_id,
          o.exit_exchange_order_id,
          o.symbol,
          o.side,
          o.entry_price,
          o.exit_price,
          o.quantity,
          o.pnl_usd,
          o.pnl_pct,
          o.exit_reason,
          o.label,
          o.entry_ts,
          o.exit_ts,
          o.hold_seconds,
          m.context_json,
          m.timestamp AS alert_timestamp,
          m.message AS alert_message
        FROM trade_outcomes o
        INNER JOIN telegram_messages m ON m.id = o.telegram_message_id
        WHERE o.join_status = 'COMPLETE'
          AND o.label IS NOT NULL
          AND o.telegram_message_id IS NOT NULL
          AND (o.entry_ts IS NULL OR o.entry_ts >= :cutoff)
        ORDER BY o.entry_ts DESC NULLS LAST
        LIMIT :lim
        """
    )
    sql_sqlite = text(
        """
        SELECT
          o.telegram_message_id,
          o.order_intent_id,
          o.entry_exchange_order_id,
          o.exit_exchange_order_id,
          o.symbol,
          o.side,
          o.entry_price,
          o.exit_price,
          o.quantity,
          o.pnl_usd,
          o.pnl_pct,
          o.exit_reason,
          o.label,
          o.entry_ts,
          o.exit_ts,
          o.hold_seconds,
          m.context_json,
          m.timestamp AS alert_timestamp,
          m.message AS alert_message
        FROM trade_outcomes o
        INNER JOIN telegram_messages m ON m.id = o.telegram_message_id
        WHERE o.join_status = 'COMPLETE'
          AND o.label IS NOT NULL
          AND o.telegram_message_id IS NOT NULL
          AND (o.entry_ts IS NULL OR o.entry_ts >= :cutoff)
        ORDER BY o.entry_ts DESC
        LIMIT :lim
        """
    )
    q = sql_sqlite if engine.dialect.name == "sqlite" else sql
    rows: list[dict[str, Any]] = []
    with engine.connect() as conn:
        for r in conn.execute(q, {"cutoff": cutoff, "lim": limit}):
            d = dict(r._mapping)
            # Prefer alert timestamp when entry_ts missing
            if d.get("entry_ts") is None and d.get("alert_timestamp") is not None:
                d["entry_ts"] = d["alert_timestamp"]
            rows.append(d)
    return rows


def _build_alert_dataset(
    alerts: list[dict[str, Any]], *, fixture: bool, delta: float
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    labeled, summary = evaluate_alerts(alerts, fixture_candles=fixture, delta=delta)
    raw_by_id: dict[Any, dict[str, Any]] = {}
    for a in alerts:
        if a.get("id") is not None:
            raw_by_id[a["id"]] = a
    for a in alerts:
        norm = normalize_alert(a)
        if norm is None:
            continue
        for row in labeled:
            if row.get("id") == a.get("id") and "context_json" not in row:
                row["context_json"] = a.get("context_json")
    dataset = attach_features_and_label(labeled, raw_by_id=raw_by_id)
    return dataset, summary


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build Auto ML entry training dataset (offline)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    src.add_argument("--api-url")
    src.add_argument("--alerts-json", type=Path)
    src.add_argument("--demo", action="store_true", help="Built-in rich demo + fixture candles")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--delta", type=float, default=DEFAULT_DELTA)
    p.add_argument("--fixture-candles", action="store_true")
    p.add_argument(
        "--label-source",
        choices=("alert", "trade_outcomes", "hybrid"),
        default="alert",
        help=(
            "alert=OHLCV forward labels (Phase 0); "
            "trade_outcomes=COMPLETE fill PnL only (Phase 1b); "
            "hybrid=prefer fills, else alert labels"
        ),
    )
    p.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "docs" / "analysis" / "auto-ml-dataset.json",
    )
    p.add_argument("--api-token", default=os.environ.get("ATP_API_TOKEN"))
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    fixture = bool(args.fixture_candles or args.demo)
    source = "demo"
    label_source = args.label_source

    if args.demo:
        if label_source != "alert":
            print(
                "--demo only supports --label-source alert "
                "(use --database-url for trade_outcomes/hybrid).",
                file=sys.stderr,
            )
            return 2
        alerts = build_rich_demo_alerts()
        fixture = True
        source = "demo+fixture"
    elif args.alerts_json:
        if label_source != "alert":
            print(
                "--alerts-json only supports --label-source alert "
                "(trade labels need --database-url).",
                file=sys.stderr,
            )
            return 2
        alerts = load_alerts_from_json(args.alerts_json)
        source = f"json:{args.alerts_json}"
    elif args.api_url:
        if label_source != "alert":
            print(
                "--api-url only supports --label-source alert "
                "(trade_outcomes live in the DB — use --database-url).",
                file=sys.stderr,
            )
            return 2
        alerts = load_alerts_from_api(args.api_url, days=args.days, token=args.api_token)
        source = f"api:{args.api_url}"
    elif args.database_url:
        alerts = [] if label_source == "trade_outcomes" else load_alerts_from_db(
            args.database_url, days=args.days
        )
        source = "database"
    else:
        print(
            "No alert source. Use --demo, --alerts-json, --api-url, or --database-url.",
            file=sys.stderr,
        )
        return 2

    summary: dict[str, Any] = {}
    alert_dataset: list[dict[str, Any]] = []
    trade_dataset: list[dict[str, Any]] = []

    if label_source in ("alert", "hybrid") and alerts:
        alert_dataset, summary = _build_alert_dataset(
            alerts, fixture=fixture, delta=args.delta
        )

    if label_source in ("trade_outcomes", "hybrid"):
        if not args.database_url:
            print(
                "--label-source trade_outcomes/hybrid requires --database-url "
                "(or DATABASE_URL).",
                file=sys.stderr,
            )
            return 2
        try:
            outcomes = load_complete_outcomes_with_alerts(
                args.database_url, days=args.days
            )
        except Exception as exc:
            print(f"Failed to load trade_outcomes: {exc}", file=sys.stderr)
            return 2
        trade_dataset = attach_features_from_trade_outcomes(outcomes)
        source = f"{source}+trade_outcomes"

    if label_source == "alert":
        dataset = alert_dataset
        label_def = ALERT_LABEL_DEF
        phase = "ml-a-offline"
    elif label_source == "trade_outcomes":
        dataset = trade_dataset
        label_def = TRADE_OUTCOME_LABEL_DEF
        phase = "1b-trade-outcomes"
    else:
        dataset = merge_alert_and_trade_datasets(alert_dataset, trade_dataset)
        label_def = HYBRID_LABEL_DEF
        phase = "1b-hybrid"

    pos = sum(1 for r in dataset if r["y"] == 1)
    neg = sum(1 for r in dataset if r["y"] == 0)
    n_trade = sum(1 for r in dataset if r.get("label_source") == "trade_outcome")
    n_alert = sum(1 for r in dataset if r.get("label_source") == "alert")

    payload = {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "delta": args.delta,
            "fixture_candles": fixture,
            "feature_version": FEATURE_VERSION,
            "feature_names": list(FEATURE_NAMES),
            "label_source": label_source,
            "label_def": label_def,
            "phase": phase,
            "n_input_alerts": len(alerts),
            "n_labeled_metrics": summary.get("n_labeled"),
            "n_trade_outcome_rows": len(trade_dataset),
            "n_alert_path_rows": len(alert_dataset),
            "n_dataset_rows": len(dataset),
            "n_from_trade_outcome": n_trade,
            "n_from_alert": n_alert,
            "n_positive": pos,
            "n_negative": neg,
        },
        "rows": dataset,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, default=str) + "\n", encoding="utf-8")
    print(
        f"Wrote {len(dataset)} rows "
        f"({pos} pos / {neg} neg; trade={n_trade} alert={n_alert}) → {args.out}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
