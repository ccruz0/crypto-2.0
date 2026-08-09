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

from alert_quality_metrics import parse_context_json, parse_indicators_from_message, to_utc_ms  # noqa: E402
from auto_ml_features import (  # noqa: E402
    _context_has_indicator_keys,
    _symbol_base,
    enrich_outcomes_with_nearest_signal_context,
    features_from_alert_row,
    features_look_default,
)
from build_auto_ml_dataset import load_complete_outcomes_with_alerts  # noqa: E402
from eval_alert_quality import load_alerts_from_db  # noqa: E402


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


def _donor_pool_report(alerts: list[dict[str, Any]]) -> dict[str, Any]:
    from auto_ml_features import _alert_has_usable_indicators

    donor_keys: Counter[str] = Counter()
    with_ind = 0
    with_msg_ind = 0
    samples: list[dict[str, Any]] = []
    for a in alerts:
        ctx = parse_context_json(a.get("context_json"))
        msg = str(a.get("message") or "")
        parsed = parse_indicators_from_message(msg)
        if parsed:
            with_msg_ind += 1
        if _alert_has_usable_indicators(a):
            with_ind += 1
            if len(samples) < 3:
                samples.append(
                    {
                        "id": a.get("id"),
                        "symbol": a.get("symbol"),
                        "keys": _ctx_keys(ctx, max_keys=20),
                        "parsed_from_message": parsed,
                        "message_preview": msg[:220],
                    }
                )
        for k in _ctx_keys(ctx, max_keys=30):
            donor_keys[k] += 1
        for k in parsed:
            donor_keys[f"msg.{k}"] += 1
    return {
        "n_signal_alerts": len(alerts),
        "n_with_indicator_keys": with_ind,
        "n_with_message_indicators": with_msg_ind,
        "top_keys": donor_keys.most_common(25),
        "indicator_samples": samples,
    }


def _match_trials(
    outcomes: list[dict[str, Any]],
    alerts: list[dict[str, Any]],
    *,
    sample: int = 5,
    windows_h: tuple[int, ...] = (6, 24, 168),
) -> list[dict[str, Any]]:
    """For sample fills, report nearest prior SIGNAL by symbol regardless of RSI keys."""
    by_base: dict[str, list[tuple[int, dict[str, Any]]]] = {}
    for alert in alerts:
        ts_ms = to_utc_ms(alert.get("timestamp"))
        if ts_ms is None:
            continue
        base = _symbol_base(alert.get("symbol"))
        if not base:
            continue
        by_base.setdefault(base, []).append((int(ts_ms), alert))
    for base in by_base:
        by_base[base].sort(key=lambda x: x[0])

    trials: list[dict[str, Any]] = []
    for oc in outcomes[:sample]:
        entry_ms = to_utc_ms(oc.get("entry_ts") or oc.get("alert_timestamp"))
        base = _symbol_base(oc.get("symbol"))
        row: dict[str, Any] = {
            "fill_tid": oc.get("telegram_message_id"),
            "symbol": oc.get("symbol"),
            "base": base,
            "entry_ts": str(oc.get("entry_ts") or oc.get("alert_timestamp")),
            "candidates_same_base": len(by_base.get(base or "", [])),
            "windows": {},
        }
        if entry_ms is None or not base:
            row["error"] = "missing_entry_or_symbol"
            trials.append(row)
            continue
        priors = [p for p in by_base.get(base, []) if p[0] <= int(entry_ms)]
        for hours in windows_h:
            max_skew_ms = hours * 3600 * 1000
            in_win = [p for p in priors if int(entry_ms) - p[0] <= max_skew_ms]
            best = in_win[-1] if in_win else None
            if best is None:
                row["windows"][f"{hours}h"] = {"n": 0}
            else:
                donor = best[1]
                dctx = parse_context_json(donor.get("context_json"))
                row["windows"][f"{hours}h"] = {
                    "n": len(in_win),
                    "donor_id": donor.get("id"),
                    "skew_min": round((int(entry_ms) - best[0]) / 60000.0, 1),
                    "has_indicator_keys": _context_has_indicator_keys(dctx),
                    "donor_keys": _ctx_keys(dctx, max_keys=15),
                }
        # Nearest prior any time
        if priors:
            best = priors[-1]
            dctx = parse_context_json(best[1].get("context_json"))
            row["nearest_any"] = {
                "donor_id": best[1].get("id"),
                "skew_h": round((int(entry_ms) - best[0]) / 3600000.0, 2),
                "has_indicator_keys": _context_has_indicator_keys(dctx),
                "donor_keys": _ctx_keys(dctx, max_keys=15),
            }
        trials.append(row)
    return trials


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Diag Auto ML fill feature degradation")
    p.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    p.add_argument("--days", type=int, default=90)
    p.add_argument("--sample", type=int, default=5)
    args = p.parse_args(argv)
    if not args.database_url:
        print("--database-url / DATABASE_URL required", file=sys.stderr)
        return 2

    raw_outcomes = load_complete_outcomes_with_alerts(
        args.database_url, days=args.days, telegram_message_ids=None
    )
    alerts = load_alerts_from_db(args.database_url, days=args.days)
    donor_pool = _donor_pool_report(alerts)
    match_trials = _match_trials(raw_outcomes, alerts, sample=args.sample)
    outcomes, enrich_stats = enrich_outcomes_with_nearest_signal_context(
        raw_outcomes, alerts, max_skew_seconds=6 * 3600
    )

    # Without alert / null label COMPLETE rows — dump for ops root-cause.
    orphan_rows: list[dict[str, Any]] = []
    try:
        from sqlalchemy import create_engine, text

        eng = create_engine(args.database_url)
        with eng.connect() as conn:
            complete_total = conn.execute(
                text("SELECT COUNT(*) FROM trade_outcomes WHERE join_status = 'COMPLETE'")
            ).scalar()
            orphan_sql = text(
                """
                SELECT
                  o.id AS trade_outcome_id,
                  o.telegram_message_id,
                  o.order_intent_id,
                  o.entry_exchange_order_id,
                  o.exit_exchange_order_id,
                  o.symbol,
                  o.side,
                  o.entry_price,
                  o.exit_price,
                  o.pnl_usd,
                  o.label,
                  o.exit_reason,
                  o.entry_ts,
                  o.exit_ts,
                  o.join_status,
                  o.source,
                  o.meta_json,
                  i.signal_id AS intent_signal_id,
                  i.status AS intent_status,
                  i.created_at AS intent_created_at
                FROM trade_outcomes o
                LEFT JOIN order_intents i ON i.id = o.order_intent_id
                WHERE o.join_status = 'COMPLETE'
                  AND (o.telegram_message_id IS NULL OR o.label IS NULL)
                ORDER BY o.entry_ts DESC NULLS LAST
                LIMIT 20
                """
            )
            for r in conn.execute(orphan_sql):
                d = dict(r._mapping)
                # Suggest nearest prior SIGNAL by symbol (message has RSI=) for backfill ideas
                base = _symbol_base(d.get("symbol"))
                entry_ms = to_utc_ms(d.get("entry_ts"))
                suggestion = None
                if base and entry_ms is not None:
                    best = None
                    for a in alerts:
                        if _symbol_base(a.get("symbol")) != base:
                            continue
                        ts = to_utc_ms(a.get("timestamp"))
                        if ts is None or ts > int(entry_ms):
                            continue
                        skew = int(entry_ms) - int(ts)
                        if skew > 24 * 3600 * 1000:
                            continue
                        msg = str(a.get("message") or "")
                        parsed = parse_indicators_from_message(msg)
                        if "rsi" not in parsed:
                            continue
                        if best is None or ts > best[0]:
                            best = (ts, a, parsed, skew)
                    if best is not None:
                        suggestion = {
                            "telegram_id": best[1].get("id"),
                            "skew_min": round(best[3] / 60000.0, 1),
                            "rsi": best[2].get("rsi"),
                            "message_preview": str(best[1].get("message") or "")[:180],
                        }
                d["suggested_signal"] = suggestion
                # Serialize datetimes
                for k, v in list(d.items()):
                    if hasattr(v, "isoformat"):
                        d[k] = v.isoformat()
                orphan_rows.append(d)
            no_alert = len(orphan_rows)
            # Prefer DB count when orphans exceed LIMIT
            cnt = conn.execute(
                text(
                    """
                    SELECT COUNT(*) FROM trade_outcomes
                    WHERE join_status = 'COMPLETE'
                      AND (telegram_message_id IS NULL OR label IS NULL)
                    """
                )
            ).scalar()
            if cnt is not None:
                no_alert = cnt
    except Exception as exc:
        no_alert = f"err:{exc}"
        complete_total = None
        orphan_rows = [{"error": str(exc)}]

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
        "orphan_complete_rows": orphan_rows,
        "loaded_with_alert_join": len(outcomes),
        "donor_pool": donor_pool,
        "match_trials": match_trials,
        "signal_ctx_enrich": enrich_stats,
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
