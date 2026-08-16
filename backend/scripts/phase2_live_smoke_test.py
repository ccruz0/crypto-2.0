#!/usr/bin/env python3
"""Phase 2 live smoke test — run on the server with real AWS credentials.

    cd backend && python scripts/phase2_live_smoke_test.py

Cost: two tiny Bedrock requests, well under $0.01. Exit code 0 = all PASS.

Checks:
  1. Text path      — ask_bedrock() returns a real Converse response.
  2. Structured path — ask_bedrock_json() returns a parsed dict via forced
                       tool-use (no text-to-JSON parsing exists in this path).
  3. Router         — the resolved model for the 'simple' tier is the Haiku
                       tier model (unless pinned/overridden by env).
  4. Cost tracking  — both calls produced records with non-zero tokens, in
                       the in-memory summary and the JSONL log.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

os.environ.setdefault("JARVIS_COST_LOG", "var/phase2_smoke_cost.jsonl")

from app.jarvis import cost_tracker  # noqa: E402
from app.jarvis.bedrock_client import ask_bedrock, ask_bedrock_json  # noqa: E402
from app.jarvis.model_router import resolve_model  # noqa: E402


def main() -> int:
    cost_tracker.reset_summary()
    log_path = os.environ["JARVIS_COST_LOG"]
    if os.path.exists(log_path):
        os.remove(log_path)

    results: list[tuple[str, bool, str]] = []

    # 1 — text path
    text = ask_bedrock("Reply with exactly the word: pong")
    ok = bool(text)
    results.append(("text path (ask_bedrock)", ok, repr(text[:80])))

    # 2 — structured path
    obj = ask_bedrock_json(
        "Give a trading recommendation for BTC as JSON with keys: "
        "symbol (string), action (buy|sell|hold), confidence (0..1).",
        schema={
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "action": {"type": "string", "enum": ["buy", "sell", "hold"]},
                "confidence": {"type": "number"},
            },
            "required": ["symbol", "action", "confidence"],
        },
        task="simple",
        agent="smoke",
        mission_id="phase2-smoke",
    )
    ok = isinstance(obj, dict) and obj.get("action") in {"buy", "sell", "hold"}
    results.append(("structured path (ask_bedrock_json)", ok, repr(obj)))

    # 3 — router resolution
    resolved = resolve_model("simple")
    pinned = bool((os.environ.get("JARVIS_BEDROCK_MODEL_ID") or "").strip())
    ok = pinned or "haiku" in resolved.lower()
    results.append(("router simple->haiku (or pinned)", ok, resolved))

    # 4 — cost records
    summary = cost_tracker.get_summary()
    jsonl_lines = 0
    if os.path.exists(log_path):
        with open(log_path, encoding="utf-8") as fh:
            jsonl_lines = sum(1 for _ in fh)
    ok = summary["records"] >= 2 and summary["input_tokens"] > 0 and jsonl_lines >= 2
    results.append(
        ("cost tracking (2+ records, non-zero tokens, JSONL)", ok,
         f"records={summary['records']} in={summary['input_tokens']} out={summary['output_tokens']} jsonl={jsonl_lines}"),
    )

    print("=" * 64)
    all_ok = True
    for name, passed, detail in results:
        print(f"[{'PASS' if passed else 'FAIL'}] {name}\n       {detail}")
        all_ok = all_ok and passed
    print("=" * 64)
    print("LIVE SMOKE TEST:", "ALL PASSED" if all_ok else "FAILED — send the full output above")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
