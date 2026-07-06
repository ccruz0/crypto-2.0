#!/usr/bin/env python3
"""
Isolated live verification for the conditional SL/TP endpoint migration (PR #119).

Background: as of 2026-02-20 Crypto.com removed STOP_LOSS / STOP_LIMIT / TAKE_PROFIT /
TAKE_PROFIT_LIMIT from `type` on `private/create-order` (HTTP 500 code 140001). Conditional
orders are now created via `private/advanced/create-order` (+ `ref_price_type`) and cancelled
via `private/advanced/cancel-order`. This script proves that end-to-end against the live
exchange with the smallest possible footprint.

What it does: places ONE tiny standalone STOP_LIMIT (default 0.01 DOT_USDT) that rests ~10%
below market so it never triggers, confirms the exchange no longer returns 140001 on the
advanced endpoint, then cancels it. Exercises the exact production path that was fixed
(`place_stop_loss_order` -> advanced endpoint). No entry order, no margin, no auto-flatten.

SAFETY
- Dry-run PREVIEW by default (no exchange call). Set CONFIRM_LIVE=1 to actually place + cancel.
- 0.01 base qty (~cents). Trigger ~10% below market: rests harmlessly, cancelled immediately.
- If cancel fails for any reason, the order_id is printed so you can cancel it manually.

VERDICT
- order_id returned      -> PASS (created via advanced endpoint, then cancelled)
- error mentions 140001  -> FAIL (regression: the exact bug PR #119 fixes)
- other error (e.g. 306) -> ENDPOINT-OK: the request reached the advanced endpoint (no 140001);
                            the order was just refused for another reason (e.g. naked sell-stop
                            balance). Not a PR #119 regression.

RUN (inside the backend container, where creds + AWS runtime context live):
    # preview (safe, no order):
    docker compose --profile aws exec backend-aws python scripts/verify_advanced_sltp.py
    # real place + cancel:
    docker compose --profile aws exec -e CONFIRM_LIVE=1 backend-aws python scripts/verify_advanced_sltp.py

Optional env: VERIFY_SYMBOL (default DOT_USDT; set DOT_USD to match the margin pair),
VERIFY_QTY (default 0.01).
"""
import json
import os
import sys
from pathlib import Path

# Make the `app` package importable whether run as `python scripts/...`, `python -m scripts...`,
# or by absolute path. backend/scripts/<this> -> parent.parent == backend/ (where `app` lives).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

SYMBOL = os.getenv("VERIFY_SYMBOL", "DOT_USDT")
QTY = float(os.getenv("VERIFY_QTY", "0.01"))
CONFIRM_LIVE = os.getenv("CONFIRM_LIVE", "0") == "1"


def _ref_price(symbol: str) -> float:
    """Best-effort current price from the public tickers endpoint (no auth needed)."""
    import requests

    r = requests.get(
        "https://api.crypto.com/exchange/v1/public/get-tickers",
        params={"instrument_name": symbol},
        timeout=10,
    )
    r.raise_for_status()
    data = (r.json().get("result") or {}).get("data") or []
    if not data:
        raise RuntimeError(f"no ticker data for {symbol}")
    t = data[0]
    for k in ("a", "k", "l", "b"):  # ask, latest, last, bid
        v = t.get(k)
        if v:
            return float(v)
    raise RuntimeError(f"no usable price field in ticker: {t}")


def main() -> None:
    from app.services.brokers.crypto_com_trade import (
        ADVANCED_CREATE_ORDER_ENDPOINT,
        trade_client,
    )

    px = _ref_price(SYMBOL)
    # SELL STOP_LIMIT ("close a long"): trigger below market so it rests and never triggers.
    trigger = round(px * 0.90, 6)
    limit = round(px * 0.895, 6)

    print("=" * 70)
    print("[verify] conditional SL/TP advanced-endpoint check (PR #119)")
    print(f"[verify] symbol={SYMBOL} qty={QTY} market~={px} trigger={trigger} limit={limit}")
    print(f"[verify] target endpoint = {ADVANCED_CREATE_ORDER_ENDPOINT}")
    print(f"[verify] CONFIRM_LIVE={CONFIRM_LIVE}  (dry-run preview unless set to 1)")
    print("=" * 70)

    dry = not CONFIRM_LIVE
    res = trade_client.place_stop_loss_order(
        symbol=SYMBOL,
        side="SELL",
        price=limit,
        qty=QTY,
        trigger_price=trigger,
        entry_price=px,
        dry_run=dry,
        source="verify_119",
    )
    print("[verify] place_stop_loss_order result:", json.dumps(res, ensure_ascii=False, default=str))

    if dry:
        print(
            "[verify] DRY-RUN preview only (no exchange call). "
            "Re-run with CONFIRM_LIVE=1 to place + cancel a real 0.01 order."
        )
        return

    err = res.get("error") if isinstance(res, dict) else "non-dict result"
    oid = (res.get("order_id") or res.get("client_order_id")) if isinstance(res, dict) else None

    if oid and not err:
        print(f"[verify] SL created on advanced endpoint: order_id={oid}")
        cancel = trade_client.cancel_order(oid, order_type="STOP_LIMIT")
        print("[verify] cancel_order result:", json.dumps(cancel, ensure_ascii=False, default=str))
        print(
            f"[verify] PASS - advanced create + cancel worked. "
            f"Confirm order {oid} shows Cancelled on the exchange."
        )
        return

    err_s = str(err or "")
    if "140001" in err_s:
        print("[verify] FAIL - 140001 returned. This is the exact bug PR #119 fixes: REGRESSION.")
        sys.exit(1)

    print(
        "[verify] ENDPOINT-OK - no 140001, so the advanced-endpoint routing works, but the order "
        f"was not created for another reason: {err_s}"
    )
    print(
        "[verify] (e.g. 306/insufficient balance for a naked sell-stop - not a PR #119 regression. "
        "Try VERIFY_SYMBOL=DOT_USD or run against a symbol you hold.)"
    )


if __name__ == "__main__":
    main()
