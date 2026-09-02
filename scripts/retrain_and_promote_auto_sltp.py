#!/usr/bin/env python3
"""Offline retrain + merit promote for Auto ML SL/TP (Phase 2 / #623).

Loads COMPLETE trade_outcomes, walk-forward grid search, writes candidate manifest.
Promote only when AUTO_ML_SLTP_HUMAN_PROMOTE=true (never autonomous by default).

Usage:
  python3 scripts/retrain_and_promote_auto_sltp.py --database-url "$DATABASE_URL" --days 90
  AUTO_ML_SLTP_HUMAN_PROMOTE=true python3 scripts/retrain_and_promote_auto_sltp.py --demo
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO_ROOT / "scripts"
_BACKEND = _REPO_ROOT / "backend"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _load_build_outcomes():
    spec = importlib.util.spec_from_file_location(
        "build_auto_ml_dataset", _SCRIPTS / "build_auto_ml_dataset.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def _next_version(out_dir: Path) -> int:
    versions: list[int] = []
    for name in ("sltp_manifest.json", "sltp_candidate_manifest.json"):
        p = out_dir / name
        if not p.is_file():
            continue
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            versions.append(int(m.get("version") or 0))
        except Exception:
            continue
    return (max(versions) + 1) if versions else 1


def load_outcomes_from_db(database_url: str, *, days: int, limit: int = 5000) -> list[dict[str, Any]]:
    build = _load_build_outcomes()
    rows = build.load_complete_outcomes_with_alerts(database_url, days=days, limit=limit)
    outcomes: list[dict[str, Any]] = []
    for r in rows:
        outcomes.append(
            {
                "symbol": r.get("symbol"),
                "side": r.get("side"),
                "entry_price": r.get("entry_price"),
                "exit_price": r.get("exit_price"),
                "exit_reason": r.get("exit_reason"),
                "pnl_pct": r.get("pnl_pct"),
                "pnl_usd": r.get("pnl_usd"),
                "hold_seconds": r.get("hold_seconds"),
                "entry_ts": r.get("entry_ts"),
                "label": r.get("label"),
                "join_status": "COMPLETE",
                "telegram_message_id": r.get("telegram_message_id"),
                "entry_exchange_order_id": r.get("entry_exchange_order_id"),
            }
        )
    return outcomes


def demo_outcomes() -> list[dict[str, Any]]:
    base = datetime.now(timezone.utc) - timedelta(days=30)
    rows: list[dict[str, Any]] = []
    specs = [
        ("BTC_USDT", "BUY", 65000.0, 66800.0, "TAKE_PROFIT", 2.77),
        ("ETH_USDT", "BUY", 3200.0, 3100.0, "STOP_LOSS", -3.12),
        ("SOL_USDT", "SELL", 140.0, 136.0, "TAKE_PROFIT", 2.86),
        ("AAVE_USD", "BUY", 95.0, 98.0, "TAKE_PROFIT", 3.16),
        ("DOT_USDT", "SELL", 6.5, 6.7, "STOP_LOSS", -3.08),
        ("LINK_USDT", "BUY", 14.0, 13.5, "STOP_LOSS", -3.57),
        ("AVAX_USDT", "BUY", 35.0, 36.2, "TAKE_PROFIT", 3.43),
        ("ATOM_USDT", "SELL", 8.0, 7.75, "TAKE_PROFIT", 3.12),
        ("NEAR_USDT", "BUY", 5.0, 5.15, "TAKE_PROFIT", 3.0),
        ("APT_USD", "BUY", 4.5, 4.35, "STOP_LOSS", -3.33),
        ("XRP_USDT", "SELL", 0.55, 0.57, "STOP_LOSS", -3.64),
        ("DOGE_USD", "BUY", 0.12, 0.1236, "TAKE_PROFIT", 3.0),
        ("LDO_USD", "BUY", 1.8, 1.74, "STOP_LOSS", -3.33),
        ("SUI_USD", "SELL", 1.2, 1.164, "TAKE_PROFIT", 3.0),
        ("TON_USD", "BUY", 5.5, 5.67, "TAKE_PROFIT", 3.09),
        ("ADA_USD", "BUY", 0.45, 0.436, "STOP_LOSS", -3.11),
        ("CRO_USD", "SELL", 0.1, 0.097, "TAKE_PROFIT", 3.0),
        ("ALGO_USD", "BUY", 0.2, 0.206, "TAKE_PROFIT", 3.0),
        ("FIL_USD", "SELL", 4.0, 4.12, "STOP_LOSS", -3.0),
        ("INJ_USD", "BUY", 20.0, 20.6, "TAKE_PROFIT", 3.0),
        ("OP_USD", "BUY", 1.5, 1.455, "STOP_LOSS", -3.0),
        ("ARB_USD", "SELL", 0.8, 0.776, "TAKE_PROFIT", 3.0),
        ("SEI_USD", "BUY", 0.3, 0.309, "TAKE_PROFIT", 3.0),
        ("TIA_USD", "SELL", 5.0, 5.15, "STOP_LOSS", -3.0),
    ]
    for i, (sym, side, entry, exit_p, reason, pnl) in enumerate(specs):
        ts = base + timedelta(hours=i * 6)
        rows.append(
            {
                "symbol": sym,
                "side": side,
                "entry_price": entry,
                "exit_price": exit_p,
                "exit_reason": reason,
                "pnl_pct": pnl,
                "join_status": "COMPLETE",
                "entry_ts": ts.isoformat(),
                "entry_exchange_order_id": f"demo-{i}",
            }
        )
    return rows


def main() -> int:
    from app.services.auto_sltp_learn import format_merit_report, walk_forward_learn
    from app.services.auto_sltp_promote import (
        apply_sltp_promote,
        clear_pending_sltp_promote,
        should_promote_sltp,
        write_pending_sltp_promote,
    )

    parser = argparse.ArgumentParser(description="Retrain + promote Auto ML SL/TP")
    parser.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    parser.add_argument("--days", type=int, default=90)
    parser.add_argument("--out-dir", type=Path, default=_REPO_ROOT / "models" / "auto_entry")
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--min-rows", type=int, default=None)
    parser.add_argument("--promote-min-rows", type=int, default=None)
    parser.add_argument("--promote-min-delta", type=float, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--force-promote", action="store_true")
    parser.add_argument("--no-telegram", action="store_true")
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.demo:
        outcomes = demo_outcomes()
        min_rows = args.min_rows or 20
    else:
        if not args.database_url:
            print("DATABASE_URL or --database-url required", file=sys.stderr)
            return 2
        outcomes = load_outcomes_from_db(args.database_url, days=args.days)
        min_rows = args.min_rows or int(os.environ.get("AUTO_ML_SLTP_PROMOTE_MIN_ROWS") or "20")

    version = _next_version(out_dir)
    result, status = walk_forward_learn(outcomes, version=version, min_rows=min_rows)
    if result is None:
        print(json.dumps({"ok": False, "reason": status, "n_outcomes": len(outcomes)}, indent=2))
        return 1

    candidate = result.to_manifest()
    report_path = out_dir / f"sltp_merit_report_v{version}.txt"
    report_path.write_text(format_merit_report(candidate) + "\n", encoding="utf-8")
    (out_dir / "sltp_candidate_manifest.json").write_text(
        json.dumps(candidate, indent=2) + "\n", encoding="utf-8"
    )

    current = None
    cur_path = out_dir / "sltp_manifest.json"
    if cur_path.is_file():
        current = json.loads(cur_path.read_text(encoding="utf-8"))

    quality = should_promote_sltp(
        candidate,
        current,
        min_rows=args.promote_min_rows,
        min_delta=args.promote_min_delta,
        force=args.force_promote,
        merit_only=True,
    )
    decision = should_promote_sltp(
        candidate,
        current,
        min_rows=args.promote_min_rows,
        min_delta=args.promote_min_delta,
        force=args.force_promote,
    )

    if quality.should_promote:
        write_pending_sltp_promote(out_dir, candidate=candidate, decision=quality)
    else:
        clear_pending_sltp_promote(out_dir)

    payload = {
        "ok": True,
        "status": status,
        "n_outcomes": len(outcomes),
        "candidate": {
            "version": candidate.get("version"),
            "sl_pct": candidate.get("sl_pct"),
            "tp_pct": candidate.get("tp_pct"),
            "merit_delta_expectancy": (candidate.get("metrics") or {}).get(
                "merit_delta_expectancy"
            ),
        },
        "quality_gate": {
            "passed": quality.should_promote,
            "reason": quality.reason,
        },
        "decision": {
            "should_promote": decision.should_promote,
            "reason": decision.reason,
        },
        "merit_report_path": str(report_path),
        "promoted": False,
        "dry_run": args.dry_run,
    }

    if decision.should_promote and not args.dry_run:
        promoted = apply_sltp_promote(out_dir, candidate_manifest=candidate, decision=decision)
        clear_pending_sltp_promote(out_dir)
        payload["promoted"] = True
        payload["promoted_version"] = promoted.get("version")
    elif quality.should_promote:
        payload["note"] = "quality_gate_passed_pending_human"
    else:
        payload["note"] = "not_promoted"

    print(json.dumps(payload, indent=2))
    print("\n--- merit report ---\n")
    print(format_merit_report(candidate))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
