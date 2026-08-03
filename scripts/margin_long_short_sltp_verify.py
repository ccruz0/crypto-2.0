#!/usr/bin/env python3
"""Production margin long+short SL/TP verification for all watchlist coins."""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional, Tuple

BASE = "https://dashboard.hilovivo.com/api"
NOTIONAL_ATTEMPTS = [1.0, 5.0, 10.0, 20.0, 50.0]
FILL_WAIT_S = 35
BETWEEN_S = 2
TICKER_URL = "https://api.crypto.com/exchange/v1/public/get-tickers"
RESULTS_PATH = "/workspace/scripts/margin_long_short_results.json"


@dataclass
class LegResult:
    symbol: str
    side: str
    amount_usd: float
    order_id: Optional[str]
    order_ok: bool
    order_error: Optional[str]
    sltp_ok: bool
    sltp_error: Optional[str]
    sl_id: Optional[str]
    tp_id: Optional[str]
    verified: bool
    verify_detail: Optional[str]


def http_json(method: str, url: str, body: Optional[dict] = None, timeout: int = 120) -> Any:
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return json.loads(raw)
        except Exception:
            return {"detail": raw or str(e), "_http_status": e.code}


def fetch_watchlist() -> List[dict]:
    items = http_json("GET", f"{BASE}/dashboard")
    if not isinstance(items, list):
        raise RuntimeError(f"Unexpected dashboard response: {items!r}")
    return items


def fetch_prices() -> Dict[str, float]:
    with urllib.request.urlopen(TICKER_URL, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    out: Dict[str, float] = {}
    for row in data.get("result", {}).get("data", []):
        inst = str(row.get("i") or row.get("instrument_name") or "").upper()
        px = row.get("a") or row.get("last") or row.get("last_price")
        if inst and px:
            try:
                out[inst] = float(px)
            except (TypeError, ValueError):
                pass
    return out


def normalize_symbol(sym: str) -> str:
    s = sym.upper().replace("/", "_")
    if "_" not in s:
        return f"{s}_USD"
    return s


def price_for(symbol: str, prices: Dict[str, float]) -> Optional[float]:
    for cand in (symbol, symbol.replace("_USDT", "_USD"), symbol.replace("_USD", "_USDT")):
        if cand in prices and prices[cand] > 0:
            return prices[cand]
    base = symbol.split("_")[0]
    for k, v in prices.items():
        if k.startswith(base + "_") and v > 0:
            return v
    return None


def place_margin_order(symbol: str, side: str, price: float) -> Tuple[bool, Optional[str], Optional[str], float]:
    last_err = None
    for amt in NOTIONAL_ATTEMPTS:
        payload = {
            "symbol": symbol,
            "side": side,
            "price": price,
            "amount_usd": amt,
            "use_margin": True,
        }
        res = http_json("POST", f"{BASE}/orders/quick", payload)
        if res.get("ok") and res.get("order_id"):
            return True, str(res["order_id"]), None, amt
        last_err = res.get("detail") or res.get("error") or json.dumps(res)[:300]
        if "BELOW_MIN_ORDER_SIZE" not in str(last_err).upper() and "MIN_ORDER" not in str(last_err).upper():
            break
        time.sleep(1)
    return False, None, str(last_err), 0.0


def create_sltp(symbol: str, entry_side: str) -> Tuple[bool, Optional[str], Optional[str], Optional[str], Optional[str]]:
    side_q = urllib.parse.quote(entry_side.upper())
    sym_q = urllib.parse.quote(symbol.upper())
    urls = [
        f"{BASE}/test/create-sl-tp-last/{sym_q}?entry_side={side_q}",
        f"{BASE}/orders/create-sl-tp-for-last-order?symbol={sym_q}&entry_side={side_q}",
    ]
    last_err = None
    for url in urls:
        res = http_json("POST", url)
        if res.get("ok") and (res.get("sl_order_id") or (res.get("creation_result") or {}).get("sl_result")):
            cr = res.get("creation_result") or res
            sl = res.get("sl_order_id") or (cr.get("sl_result") or {}).get("order_id")
            tp = res.get("tp_order_id") or (cr.get("tp_result") or {}).get("order_id")
            oid = res.get("order_id")
            ok = bool(sl) and bool(tp)
            return ok, str(oid) if oid else None, str(sl) if sl else None, str(tp) if tp else None, None
        last_err = res.get("detail") or res.get("message") or json.dumps(res)[:300]
        if res.get("_http_status") == 404 and "create-sl-tp-last" in url:
            continue
    return False, None, None, None, last_err


def verify_entry(symbol: str, parent_order_id: str, entry_side: str) -> Tuple[bool, str]:
    side_q = urllib.parse.quote(entry_side.upper())
    url = (
        f"{BASE}/test/verify-protection/{symbol.upper()}"
        f"?parent_order_id={parent_order_id}&entry_side={side_q}&minutes=180"
    )
    res = http_json("GET", url)
    if res.get("verified"):
        return True, "verified"
    return False, res.get("error") or res.get("detail") or json.dumps(res)[:200]


def run_leg(symbol: str, side: str, price: float) -> LegResult:
    ok, oid, err, amt = place_margin_order(symbol, side, price)
    result = LegResult(
        symbol=symbol,
        side=side,
        amount_usd=amt,
        order_id=oid,
        order_ok=ok,
        order_error=err,
        sltp_ok=False,
        sltp_error=None,
        sl_id=None,
        tp_id=None,
        verified=False,
        verify_detail=None,
    )
    if not ok:
        return result

    time.sleep(FILL_WAIT_S)

    entry_side = "BUY" if side == "BUY" else "SELL"
    sltp_ok, _parent, sl, tp, sltp_err = create_sltp(symbol, entry_side)
    result.sltp_ok = sltp_ok
    result.sltp_error = sltp_err
    result.sl_id = sl
    result.tp_id = tp

    if sltp_ok and oid:
        v_ok, v_detail = verify_entry(symbol, oid, entry_side)
        result.verified = v_ok
        result.verify_detail = v_detail
    elif sltp_ok:
        result.verified = True
        result.verify_detail = "sltp created (no verify id)"

    return result


def main() -> int:
    items = fetch_watchlist()
    prices = fetch_prices()
    symbols: List[str] = []
    seen = set()
    for item in items:
        sym = normalize_symbol(str(item.get("symbol") or ""))
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)

    results: List[Dict[str, Any]] = []
    summary = {
        "long_ok": 0,
        "long_fail": 0,
        "short_ok": 0,
        "short_fail": 0,
        "total_symbols": len(symbols),
    }

    print(f"Margin long+short SL/TP sweep: {len(symbols)} symbols", flush=True)

    for i, symbol in enumerate(symbols, 1):
        px = price_for(symbol, prices)
        print(f"\n[{i}/{len(symbols)}] {symbol} px={px}", flush=True)
        if not px:
            for side in ("BUY", "SELL"):
                r = LegResult(symbol, side, 0, None, False, "no_price", False, None, None, None, False, None)
                results.append(asdict(r))
                summary["long_fail" if side == "BUY" else "short_fail"] += 1
            continue

        long_r = run_leg(symbol, "BUY", px)
        results.append(asdict(long_r))
        if long_r.verified:
            summary["long_ok"] += 1
            print(f"  LONG OK ${long_r.amount_usd} sl={long_r.sl_id} tp={long_r.tp_id}", flush=True)
        else:
            summary["long_fail"] += 1
            print(f"  LONG FAIL ${long_r.amount_usd} order={long_r.order_error} sltp={long_r.sltp_error}", flush=True)

        time.sleep(BETWEEN_S)

        short_r = run_leg(symbol, "SELL", px)
        results.append(asdict(short_r))
        if short_r.verified:
            summary["short_ok"] += 1
            print(f"  SHORT OK ${short_r.amount_usd} sl={short_r.sl_id} tp={short_r.tp_id}", flush=True)
        else:
            summary["short_fail"] += 1
            print(f"  SHORT FAIL ${short_r.amount_usd} order={short_r.order_error} sltp={short_r.sltp_error}", flush=True)

        time.sleep(BETWEEN_S)
        with open(RESULTS_PATH, "w") as f:
            json.dump({"summary": summary, "results": results}, f, indent=2)

    print("\n=== FINAL SUMMARY ===", flush=True)
    print(json.dumps(summary, indent=2), flush=True)
    print(f"Saved: {RESULTS_PATH}", flush=True)
    return 0 if summary["long_fail"] == 0 and summary["short_fail"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
