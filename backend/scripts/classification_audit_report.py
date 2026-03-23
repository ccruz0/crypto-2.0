#!/usr/bin/env python3
"""
Summarize governance classification events from application log lines (JSON payloads).

Greps for structured events emitted by agent_execution_policy:
  - governance_classification_result
  - governance_classification_conflict
  - classification_uncertain_defaulted_to_prod_mutation

Usage:
  python backend/scripts/classification_audit_report.py /path/to/app.log
  grep 'governance_classification' app.log | python backend/scripts/classification_audit_report.py

  python backend/scripts/classification_audit_report.py --sample   # built-in demo lines

Does not connect to the database; use log aggregation or exported log files.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from typing import Any


EVENT_MARKERS = (
    '"event": "governance_classification_result"',
    '"event": "governance_classification_conflict"',
    '"event": "classification_uncertain_defaulted_to_prod_mutation"',
    "governance_classification_result {",
    "governance_classification_conflict {",
    "classification_uncertain_defaulted_to_prod_mutation {",
)


def _extract_json_object(line: str, start_brace: int) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    try:
        obj, _end = decoder.raw_decode(line[start_brace:])
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        return None


def parse_classification_record(line: str) -> dict[str, Any] | None:
    """If line contains a classification JSON payload, return the dict."""
    if not any(m in line for m in EVENT_MARKERS):
        return None
    # Prefer last '{' on line (handles prefixed logger text).
    brace = line.rfind("{")
    if brace < 0:
        return None
    return _extract_json_object(line, brace)


def summarize(records: list[dict[str, Any]]) -> None:
    n = len(records)
    prod = sum(1 for r in records if r.get("final_classification") == "prod_mutation" or r.get("classification_result") == "prod_mutation")
    patch = sum(1 for r in records if r.get("final_classification") == "patch_prep" or r.get("classification_result") == "patch_prep")
    uncertain = sum(1 for r in records if r.get("event") == "classification_uncertain_defaulted_to_prod_mutation")
    conflicts = sum(1 for r in records if r.get("event") == "governance_classification_conflict")
    bypass_hints = sum(1 for r in records if "bypass" in str(r.get("classification_path", "")).lower())

    reasons = Counter(str(r.get("selection_reason") or "")[:120] for r in records if r.get("selection_reason"))
    callbacks = Counter(
        f"{r.get('callback_module') or r.get('apply_module')}.{r.get('callback_name') or r.get('apply_name')}".strip(".")
        for r in records
        if (r.get("callback_name") or r.get("apply_name"))
    )

    print("Governance classification audit (from log-derived records)")
    print("=" * 60)
    print(f"Total parsed records: {n}")
    print(f"  prod_mutation (from result events): {prod}")
    print(f"  patch_prep (from result events): {patch}")
    print(f"  uncertain_defaulted_to_prod_mutation events: {uncertain}")
    print(f"  governance_classification_conflict events: {conflicts}")
    print(f"  rows with 'bypass' in classification_path: {bypass_hints}")
    print()
    print("Top selection_reason (truncated):")
    for val, cnt in reasons.most_common(12):
        if val:
            print(f"  {cnt:4d}  {val!r}")
    print()
    print("Top callback (module.name):")
    for val, cnt in callbacks.most_common(12):
        if val and val != ".":
            print(f"  {cnt:4d}  {val}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize governance classification log events.")
    parser.add_argument(
        "path",
        nargs="?",
        help="Log file path (default: read stdin)",
    )
    parser.add_argument("--sample", action="store_true", help="Run on embedded sample lines")
    args = parser.parse_args()

    if args.sample:
        lines = [
            'INFO x governance_classification_result {"event":"governance_classification_result","classification_result":"patch_prep","final_classification":"patch_prep","selection_reason":"documentation","apply_module":"app","apply_name":"fn","enforcement_active":true,"environment":"aws","classification_path":"callable_safe_lab_marker"}',
            'WARN x classification_uncertain_defaulted_to_prod_mutation {"event":"classification_uncertain_defaulted_to_prod_mutation","final_classification":"prod_mutation","selection_reason":"custom","callback_module":"x","callback_name":"y","enforcement_active":true,"environment":"aws"}',
            'ERROR x governance_classification_conflict {"event":"governance_classification_conflict","conflict_type":"explicit_patch_prep_vs_structural_prod","selection_reason":"test","explicit_class":"patch_prep","callback_module":"m","callback_name":"n","enforcement_active":true,"environment":"aws"}',
        ]
    elif args.path:
        with open(args.path, encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    else:
        lines = sys.stdin.readlines()

    records: list[dict[str, Any]] = []
    for line in lines:
        rec = parse_classification_record(line)
        if rec:
            records.append(rec)

    if not records:
        print("No classification events found.", file=sys.stderr)
        return 1
    summarize(records)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
