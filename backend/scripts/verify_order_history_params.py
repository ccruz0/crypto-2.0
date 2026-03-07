#!/usr/bin/env python3
"""
Verify which param keys are used for get-order-history and get-trades when instrument_name is provided.
No secrets, no network calls. Matches broker logic in crypto_com_trade.get_order_history.
Run: python scripts/verify_order_history_params.py
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


def build_order_history_params(
    page_size: int = 100,
    start_time: Optional[int] = None,
    end_time: Optional[int] = None,
    page: int = 0,
    instrument_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Mirror broker get_order_history param building (keys only for verification)."""
    limit = min(int(page_size or 100), 100)
    params: Dict[str, Any] = {"limit": limit}
    now_ms = int(time.time() * 1000)
    if page == 0:
        end_ms = int(end_time) if end_time is not None else now_ms
        start_ms = int(start_time) if start_time is not None else (end_ms - 180 * 24 * 60 * 60 * 1000)
        params["end_time"] = end_ms
        params["start_time"] = start_ms
    else:
        if end_time is not None:
            params["end_time"] = int(end_time)
        if start_time is not None:
            params["start_time"] = int(start_time)
    if instrument_name:
        params["instrument_name"] = instrument_name
    return params


def build_get_trades_params(
    limit: int,
    start_time: int,
    end_time: int,
    instrument_name: Optional[str] = None,
) -> Dict[str, Any]:
    """Mirror broker get-trades fallback param building."""
    trades_params: Dict[str, Any] = {
        "limit": limit,
        "start_time": start_time,
        "end_time": end_time,
    }
    if instrument_name:
        trades_params["instrument_name"] = instrument_name
    return trades_params


def main() -> None:
    print("=== get-order-history param keys (page=0) ===\n")
    # Without instrument_name
    p1 = build_order_history_params(page_size=100, page=0, instrument_name=None)
    keys1 = sorted(p1.keys())
    print("instrument_name=None:", keys1)
    print("params_count =", len(keys1), "(expected 3: limit, start_time, end_time)\n")
    # With instrument_name
    p2 = build_order_history_params(page_size=100, page=0, instrument_name="BCH_USDT")
    keys2 = sorted(p2.keys())
    print("instrument_name='BCH_USDT':", keys2)
    print("params_count =", len(keys2), "(expected 4: + instrument_name)\n")

    print("=== get-trades param keys ===\n")
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - 180 * 24 * 60 * 60 * 1000
    pt1 = build_get_trades_params(limit=100, start_time=start_ms, end_time=now_ms, instrument_name=None)
    print("instrument_name=None:", sorted(pt1.keys()))
    pt2 = build_get_trades_params(limit=100, start_time=start_ms, end_time=now_ms, instrument_name="BCH_USDT")
    print("instrument_name='BCH_USDT':", sorted(pt2.keys()))

    # Verify params_to_str would include keys in sorted order (signing)
    def params_to_str_sorted(params: dict) -> str:
        if not params:
            return ""
        return "".join(str(k) + str(params[k]) for k in sorted(params.keys()))

    print("\n=== params_to_str (sorted keys) includes instrument_name when set ===\n")
    s1 = params_to_str_sorted(p1)
    s2 = params_to_str_sorted(p2)
    print("order_history (no instrument_name) string length:", len(s1))
    print("order_history (with instrument_name) string length:", len(s2))
    assert "instrument_name" not in s1 or "BCH_USDT" not in s1
    assert "instrument_name" in s2 and "BCH_USDT" in s2
    print("OK: instrument_name appears in signed string only when provided.")


if __name__ == "__main__":
    main()
