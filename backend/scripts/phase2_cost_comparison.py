#!/usr/bin/env python3
"""Phase 2 (P2-R3): before/after cost comparison — the acceptance artifact.

    cd backend && python scripts/phase2_cost_comparison.py
    cd backend && python scripts/phase2_cost_comparison.py --log var/phase2_smoke_cost.jsonl

Without --log it produces the modelled comparison (identical token profile,
legacy single-model routing vs Phase 2 tiered routing). With --log it uses the
real measured token counts from the cost tracker JSONL (e.g. produced by the
live smoke test or live traffic) and re-prices them both ways.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.jarvis.cost_tracker import estimate_cost_usd  # noqa: E402

HAIKU = "anthropic.claude-3-haiku-20240307-v1:0"
SONNET = "anthropic.claude-3-sonnet-20240229-v1:0"

# Modelled monthly workload when no measured log is supplied.
MODELLED_WORKLOAD = [
    # (label, tier, calls, input_tokens, output_tokens)
    ("classification / short extraction", "simple", 3000, 800, 200),
    ("planning / research / strategy", "standard", 800, 2500, 900),
]


def _pct(a: float, b: float) -> float:
    return 0.0 if b <= 0 else (1 - a / b) * 100.0


def modelled_report() -> dict:
    rows = []
    before_total = after_total = 0.0
    for label, tier, calls, tin, tout in MODELLED_WORKLOAD:
        before = calls * estimate_cost_usd(SONNET, tin, tout)  # legacy: everything on Sonnet
        after_model = HAIKU if tier == "simple" else SONNET
        after = calls * estimate_cost_usd(after_model, tin, tout)
        rows.append({
            "workload": label, "tier": tier, "calls": calls,
            "before_usd": round(before, 4), "after_usd": round(after, 4),
            "saving_pct": round(_pct(after, before), 1),
        })
        before_total += before
        after_total += after
    return {"rows": rows, "before_total_usd": round(before_total, 4),
            "after_total_usd": round(after_total, 4),
            "total_saving_pct": round(_pct(after_total, before_total), 1)}


def measured_report(log_path: str) -> dict:
    rows = []
    before_total = after_total = 0.0
    with open(log_path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            tin, tout = int(rec.get("input_tokens") or 0), int(rec.get("output_tokens") or 0)
            before = estimate_cost_usd(SONNET, tin, tout)          # legacy pricing
            after = estimate_cost_usd(str(rec.get("model_id") or SONNET), tin, tout)  # routed pricing
            rows.append({
                "agent": rec.get("agent"), "task": rec.get("task"),
                "model_id": rec.get("model_id"),
                "input_tokens": tin, "output_tokens": tout,
                "before_usd": round(before, 6), "after_usd": round(after, 6),
            })
            before_total += before
            after_total += after
    return {"rows": rows, "before_total_usd": round(before_total, 6),
            "after_total_usd": round(after_total, 6),
            "total_saving_pct": round(_pct(after_total, before_total), 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="cost tracker JSONL with measured usage")
    ap.add_argument("--out", default="var/phase2_cost_comparison.json")
    args = ap.parse_args()

    classification_saving = _pct(estimate_cost_usd(HAIKU, 1000, 1000),
                                 estimate_cost_usd(SONNET, 1000, 1000))

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "measured" if args.log else "modelled",
        "classification_tier_saving_identical_tokens_pct": round(classification_saving, 1),
        "committed_range_pct": "60-80",
    }
    report.update(measured_report(args.log) if args.log else modelled_report())

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fh:
        json.dump(report, fh, indent=2)

    print(f"Phase 2 cost comparison ({report['mode']})")
    print(f"  classification-tier saving (identical tokens): {report['classification_tier_saving_identical_tokens_pct']}%"
          f"  [committed: {report['committed_range_pct']}%]")
    print(f"  before total: ${report['before_total_usd']}   after total: ${report['after_total_usd']}"
          f"   overall saving: {report['total_saving_pct']}%")
    print(f"  written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
