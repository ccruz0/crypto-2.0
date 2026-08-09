#!/usr/bin/env python3
"""Read-only prod diag: why COMPLETE fills look feature-degraded for Auto ML.

Usage:
  python3 scripts/diag_auto_ml_fill_features.py --database-url "$DATABASE_URL" --days 90
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Optional

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _REPO_ROOT / "scripts"
for p in (_SCRIPTS,):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from alert_quality_metrics import parse_context_json  # noqa: E402
from auto_ml_features import (  # noqa: E402
    features_from_alert_row,
    features_look_default,
    to_utc_ms,
)
from build_auto_ml_dataset import load_complete_outcomes_with_alerts  # noqa: E402


def _f_entry(oc: dict[str, Any]) -> float:
    try:
        return float(oc.get("entry_price") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _ctx_keys(ctx: dict[str, Any], *, max_keys: int = 40) -> list[str]:
    keys = sorted(str(k) for k in ctx.keys())
    ind = ctx.get("indicators")
    if isinstance(ind, dict):
        keys.extend(f"indicators.{k}" for k in sorted(ind.keys())[:20])
    return keys[:max_keys]


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Diag Auto ML fill feature degradation")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--sample", type=int, default=5)
    args = p.parse_args(argv)
    if not args.database_url:
        print("--database-url / DATABASE_URL required", file=sys.stderr)
        return 2

    outcomes = load_complete_outcomes_with_alerts(
        args.database_url, days=args.days, telegram_message_ids=None
    )

    # Without alert = COMPLETE rows missing telegram join target
    try:
        from sqlalchemy import create_engine, text

        eng = create_engine(args.database_url)
        with eng.connect() as conn:
            no_alert = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM trade_outcomes
                    WHERE join_status = 'COMPLETE'
                      AND (telegram_message_id IS NULL OR label IS NULL)
                    """
                )
            ).scalar()
            complete_total = conn.execute(
                text("SELECT COUNT(*) FROM trade_outcomes WHERE join_status = 'COMPLETE'")
            ).scalar()
    except Exception as exc:
        no_alert = f"err:{exc}"
        complete_total = None

    degraded = 0
    rich = 0
    empty_parse = 0
    key_counter: Counter[str] = Counter()
    samples: list[dict[str, Any]] = []

    for oc in outcomes:
        raw_ctx = oc.get("context_json")
        ctx = parse_context_json(raw_ctx)
        if not ctx:
            empty_parse += 1
        for k in _ctx_keys(ctx):
            key_counter[k] += 1

        side = str(oc.get("side") or "BUY").upper()
        entry_price = _f_entry(oc)
        entry_ts = oc.get("entry_ts") or oc.get("alert_timestamp")
        feats = features_from_alert_row(
            {
                "id": oc.get("telegram_message_id"),
                "timestamp": entry_ts,
                "context_json": raw_ctx or {},
                "side": side,
                "entry_price": entry_price,
            },
            normalized={
                "side": side,
                "entry_price": entry_price,
                "entry_ts_ms": to_utc_ms(entry_ts),
            },
        )
        is_def = features_look_default(feats)
        if is_def:
            degraded += 1
            if len(samples) < args.sample:
                samples.append(
                    {
                        "telegram_message_id": oc.get("telegram_message_id"),
                        "symbol": oc.get("symbol"),
                        "side": side,
                        "entry_price": entry_price,
                        "label": oc.get("label"),
                        "ctx_top_keys": _ctx_keys(ctx, max_keys=25),
                        "ctx_type": type(raw_ctx).__name__,
                        "ctx_len": len(raw_ctx) if isinstance(raw_ctx, (str, bytes)) else None,
                        "feats": {
                            k: feats.get(k)
                            for k in ("rsi", "ma50_dist", "ma200_dist", "ema10_dist", "atr_pct")
                        },
                        "raw_ctx_preview": (
                            (raw_ctx[:400] if isinstance(raw_ctx, str) else None)
                            or (
                                json.dumps(ctx, default=str)[:400]
                                if ctx
                                else None
                            )
                        ),
                    }
                )
        else:
            rich += 1

    summary = {
        "days": args.days,
        "complete_total_db": complete_total,
        "complete_no_alert_or_null_label": no_alert,
        "loaded_with_alert_join": len(outcomes),
        "feature_rich": rich,
        "feature_degraded": degraded,
        "context_parse_empty": empty_parse,
        "top_ctx_keys": key_counter.most_common(25),
        "degraded_samples": samples,
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
