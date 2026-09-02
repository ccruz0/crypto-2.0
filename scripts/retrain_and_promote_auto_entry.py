#!/usr/bin/env python3
"""Retrain Auto entry model and optionally promote current.joblib (PR-ML-C).

Flow:
  1) Optionally rebuild dataset (--demo / --api-url / --database-url / existing JSON)
  2) Train candidate (--no-promote train path)
  3) Decide promote via auto_entry_promote.should_promote
  4) If AUTO_ML_HUMAN_PROMOTE=true or AUTO_ML_AUTONOMOUS_PROMOTE=true (or --force-promote):
     apply_promote + Telegram

Does not mutate trading_config. Live BUY gate still requires AUTO_ML_ENABLED.
Production keeps AUTO_ML_AUTONOMOUS_PROMOTE=false; operators use AUTO_ML_HUMAN_PROMOTE
via workflow_dispatch dry_run_only=false.

Usage:
  python3 scripts/retrain_and_promote_auto_entry.py --demo --min-rows 4 \\
    --promote-min-rows 4 --allow-single-class
  AUTO_ML_HUMAN_PROMOTE=true python3 scripts/retrain_and_promote_auto_entry.py --demo ...
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Optional

_SCRIPTS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _SCRIPTS_DIR.parent
_BACKEND = _REPO_ROOT / "backend"
for p in (_SCRIPTS_DIR, _BACKEND):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from build_auto_ml_dataset import main as build_main  # noqa: E402
from train_auto_entry_model import main as train_main  # noqa: E402

# Load promote helpers without importing app.services.__init__ (avoids heavy deps).
import importlib.util  # noqa: E402

_promote_path = _BACKEND / "app" / "services" / "auto_entry_promote.py"
_spec = importlib.util.spec_from_file_location("auto_entry_promote", _promote_path)
if _spec is None or _spec.loader is None:
    raise SystemExit(f"Cannot load {_promote_path}")
_promote = importlib.util.module_from_spec(_spec)
sys.modules["auto_entry_promote"] = _promote
_spec.loader.exec_module(_promote)
apply_promote = _promote.apply_promote
clear_pending_promote = _promote.clear_pending_promote
load_manifest = _promote.load_manifest
load_pending_promote = _promote.load_pending_promote
notify_model_version_update = _promote.notify_model_version_update
should_promote = _promote.should_promote
write_pending_promote = _promote.write_pending_promote


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Retrain + optional autonomous promote (PR-ML-C)")
    src = p.add_mutually_exclusive_group()
    src.add_argument("--demo", action="store_true")
    src.add_argument("--dataset", type=Path, help="Existing dataset JSON (skip build)")
    src.add_argument("--api-url")
    src.add_argument("--database-url", default=os.environ.get("DATABASE_URL"))
    src.add_argument("--alerts-json", type=Path)
    p.add_argument("--days", type=int, default=30)
    p.add_argument(
        "--label-source",
        choices=("alert", "trade_outcomes", "hybrid"),
        default="alert",
        help="Dataset labels: alert | trade_outcomes | hybrid (prefer executed fills)",
    )
    p.add_argument(
        "--out-dir",
        type=Path,
        default=_REPO_ROOT / "models" / "auto_entry",
    )
    p.add_argument(
        "--dataset-out",
        type=Path,
        default=_REPO_ROOT / "docs" / "analysis" / "auto-ml-dataset.json",
    )
    p.add_argument("--min-rows", type=int, default=6)
    p.add_argument("--promote-min-rows", type=int, default=None)
    p.add_argument("--promote-min-delta", type=float, default=None)
    p.add_argument("--allow-single-class", action="store_true")
    p.add_argument(
        "--force-promote",
        action="store_true",
        help="Promote even if AUTO_ML_AUTONOMOUS_PROMOTE is false / metrics flat",
    )
    p.add_argument("--dry-run", action="store_true", help="Decide only; never write current.joblib")
    p.add_argument("--no-telegram", action="store_true")
    p.add_argument("--test-size", type=float, default=0.25)
    p.add_argument("--seed", type=int, default=42)
    return p.parse_args(argv)


def _build_dataset(args: argparse.Namespace) -> Path:
    if args.dataset:
        print("AUTO_ML_RETRAIN_HEARTBEAT using_existing_dataset path=" + str(args.dataset), file=sys.stderr, flush=True)
        return args.dataset
    print(
        f"AUTO_ML_RETRAIN_HEARTBEAT build_dataset_start label_source={args.label_source} days={args.days}",
        file=sys.stderr,
        flush=True,
    )
    build_argv: list[str] = [
        "--out",
        str(args.dataset_out),
        "--label-source",
        args.label_source,
    ]
    if args.demo:
        if args.label_source != "alert":
            print("--demo requires --label-source alert", file=sys.stderr)
            raise SystemExit(2)
        build_argv.append("--demo")
    elif args.alerts_json:
        build_argv.extend(["--alerts-json", str(args.alerts_json)])
    elif args.api_url:
        build_argv.extend(["--api-url", args.api_url, "--days", str(args.days)])
    elif args.database_url:
        build_argv.extend(["--database-url", args.database_url, "--days", str(args.days)])
    else:
        print(
            "Provide --demo, --dataset, --api-url, --database-url, or --alerts-json",
            file=sys.stderr,
        )
        raise SystemExit(2)
    rc = build_main(build_argv)
    if rc != 0:
        print(f"AUTO_ML_RETRAIN_HEARTBEAT build_dataset_failed rc={rc}", file=sys.stderr, flush=True)
        raise SystemExit(rc)
    print(f"AUTO_ML_RETRAIN_HEARTBEAT build_dataset_done path={args.dataset_out}", file=sys.stderr, flush=True)
    return args.dataset_out


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    ds_path = _build_dataset(args)

    print(f"AUTO_ML_RETRAIN_HEARTBEAT train_start dataset={ds_path}", file=sys.stderr, flush=True)
    train_argv = [
        "--dataset",
        str(ds_path),
        "--out-dir",
        str(args.out_dir),
        "--min-rows",
        str(args.min_rows),
        "--test-size",
        str(args.test_size),
        "--seed",
        str(args.seed),
        "--no-promote",
    ]
    rc = train_main(train_argv)
    if rc != 0:
        print(f"AUTO_ML_RETRAIN_HEARTBEAT train_failed rc={rc}", file=sys.stderr, flush=True)
        return rc
    print("AUTO_ML_RETRAIN_HEARTBEAT train_done", file=sys.stderr, flush=True)

    candidate_manifest_path = args.out_dir / "candidate_manifest.json"
    candidate_model = args.out_dir / "candidate.joblib"
    candidate = load_manifest(candidate_manifest_path)
    if candidate is None or not candidate_model.is_file():
        print("Candidate artifacts missing after train", file=sys.stderr)
        return 2

    current = load_manifest(args.out_dir / "manifest.json")
    quality = should_promote(
        candidate,
        current,
        min_rows=args.promote_min_rows,
        min_delta=args.promote_min_delta,
        allow_single_class=args.allow_single_class,
        merit_only=True,
        force=args.force_promote,
    )
    decision = should_promote(
        candidate,
        current,
        min_rows=args.promote_min_rows,
        min_delta=args.promote_min_delta,
        allow_single_class=args.allow_single_class,
        force=args.force_promote,
    )

    if quality.should_promote:
        write_pending_promote(
            args.out_dir,
            candidate=candidate,
            decision=quality,
        )
    else:
        clear_pending_promote(args.out_dir)

    result: dict[str, Any] = {
        "candidate_version": candidate.get("version"),
        "quality_gate": {
            "passed": quality.should_promote,
            "reason": quality.reason,
            "candidate_metric": quality.candidate_metric,
            "current_metric": quality.current_metric,
        },
        "decision": {
            "should_promote": decision.should_promote,
            "reason": decision.reason,
            "candidate_metric": decision.candidate_metric,
            "current_metric": decision.current_metric,
            "autonomous": decision.autonomous,
            "human_promote": decision.human_promote,
        },
        "promoted": False,
        "dry_run": args.dry_run,
    }

    if decision.should_promote and not args.dry_run:
        previous = current
        promoted = apply_promote(
            args.out_dir,
            candidate_model=candidate_model,
            candidate_manifest=candidate,
            decision=decision,
        )
        result["promoted"] = True
        result["promoted_manifest"] = {
            "version": promoted.get("version"),
            "previous_version": promoted.get("previous_version"),
            "promoted_at": promoted.get("promoted_at"),
            "promote_reason": promoted.get("promote_reason"),
        }
        if not args.no_telegram:
            result["telegram_sent"] = notify_model_version_update(
                out_dir=args.out_dir,
                promoted=promoted,
                decision=decision,
                previous=previous,
            )
    elif quality.should_promote and args.dry_run:
        result["note"] = "quality_gate_passed_pending_human"
    elif decision.should_promote and args.dry_run:
        result["note"] = "would_promote"
    else:
        result["note"] = "not_promoted"

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
