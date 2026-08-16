"""Per-agent / per-mission Bedrock cost tracking (Phase 2 / P2-R4).

Design constraints (deliberate):
  * No database migration — this runs inside a live trading system, so we take
    zero schema risk. Records go to an append-only JSONL file plus an
    in-memory aggregate. The Phase 3 dashboard reads the JSONL directly.
  * Never raises — cost accounting must not be able to break a trading path.
  * Thread-safe — the Jarvis runner and API workers may record concurrently.

Environment:
  JARVIS_COST_LOG   path to the JSONL log (default: var/jarvis_costs.jsonl)
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()

# USD per 1K tokens (input, output). Bedrock on-demand pricing for Claude 3.
PRICING_PER_1K: dict[str, tuple[float, float]] = {
    "anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
    "anthropic.claude-3-sonnet-20240229-v1:0": (0.003, 0.015),
    "anthropic.claude-3-opus-20240229-v1:0": (0.015, 0.075),
}
_DEFAULT_PRICING = (0.003, 0.015)  # unknown model -> price as Sonnet


class _Summary:
    """In-memory aggregate, reset per process."""

    def __init__(self) -> None:
        self.records: int = 0
        self.input_tokens: int = 0
        self.output_tokens: int = 0
        self.cost_usd: float = 0.0
        self.by_agent: dict[str, dict[str, float]] = {}
        self.by_mission: dict[str, dict[str, float]] = {}
        self.by_model: dict[str, dict[str, float]] = {}


_SUMMARY = _Summary()


def _log_path() -> str:
    return (os.environ.get("JARVIS_COST_LOG") or "var/jarvis_costs.jsonl").strip()


def estimate_cost_usd(model_id: str, input_tokens: int, output_tokens: int) -> float:
    p_in, p_out = PRICING_PER_1K.get(model_id, _DEFAULT_PRICING)
    return (max(input_tokens, 0) / 1000.0) * p_in + (max(output_tokens, 0) / 1000.0) * p_out


def _bump(bucket: dict[str, dict[str, float]], key: str, tokens_in: int, tokens_out: int, cost: float) -> None:
    row = bucket.setdefault(key, {"calls": 0, "input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
    row["calls"] += 1
    row["input_tokens"] += tokens_in
    row["output_tokens"] += tokens_out
    row["cost_usd"] += cost


def record_usage(
    *,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    task: str = "standard",
    agent: str = "unknown",
    mission_id: str | None = None,
) -> dict[str, Any] | None:
    """Record one Bedrock call. Returns the record, or None if accounting failed.

    Never raises.
    """
    try:
        cost = estimate_cost_usd(model_id, input_tokens, output_tokens)
        rec: dict[str, Any] = {
            "ts": time.time(),
            "model_id": model_id,
            "task": task,
            "agent": agent or "unknown",
            "mission_id": mission_id or "",
            "input_tokens": int(input_tokens),
            "output_tokens": int(output_tokens),
            "cost_usd": round(cost, 8),
        }
        with _LOCK:
            _SUMMARY.records += 1
            _SUMMARY.input_tokens += rec["input_tokens"]
            _SUMMARY.output_tokens += rec["output_tokens"]
            _SUMMARY.cost_usd += cost
            _bump(_SUMMARY.by_agent, rec["agent"], rec["input_tokens"], rec["output_tokens"], cost)
            if rec["mission_id"]:
                _bump(_SUMMARY.by_mission, rec["mission_id"], rec["input_tokens"], rec["output_tokens"], cost)
            _bump(_SUMMARY.by_model, model_id, rec["input_tokens"], rec["output_tokens"], cost)
        _append_jsonl(rec)
        return rec
    except Exception as e:  # noqa: BLE001 — cost accounting must never break a call path
        logger.warning("cost_tracker.record_usage failed: %s", e)
        return None


def _append_jsonl(rec: dict[str, Any]) -> None:
    path = _log_path()
    try:
        directory = os.path.dirname(path)
        if directory:
            os.makedirs(directory, exist_ok=True)
        with _LOCK:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n")
    except OSError as e:
        logger.warning("cost_tracker: could not append to %s: %s", path, e)


def get_summary() -> dict[str, Any]:
    """Snapshot of the in-memory aggregate (per process)."""
    with _LOCK:
        return {
            "records": _SUMMARY.records,
            "input_tokens": _SUMMARY.input_tokens,
            "output_tokens": _SUMMARY.output_tokens,
            "cost_usd": round(_SUMMARY.cost_usd, 8),
            "by_agent": {k: dict(v) for k, v in _SUMMARY.by_agent.items()},
            "by_mission": {k: dict(v) for k, v in _SUMMARY.by_mission.items()},
            "by_model": {k: dict(v) for k, v in _SUMMARY.by_model.items()},
        }


def reset_summary() -> None:
    """Test hook: clear the in-memory aggregate."""
    global _SUMMARY
    with _LOCK:
        _SUMMARY = _Summary()
