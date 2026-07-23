#!/usr/bin/env python3
"""
Ops recovery: find entry prices and recreate missing TAKE_PROFIT (and optionally SL).

Addresses the Telegram failures:
  - Cannot determine entry price (checker only looks at exact symbol)
  - PROTECTION ORDER REJECTED / INSUFFICIENT_ACC_BALANCE on TP

Default is DRY-RUN. Use --live to place orders (also requires LIVE_TRADING=true).

Examples:
  # Diagnose symbols from the ATP Control alerts
  python3 scripts/recover_missing_tps.py

  # Specific symbols
  python3 scripts/recover_missing_tps.py ETH_USDT DOT_USDT AKT_USDT

  # Place TPs only (live)
  python3 scripts/recover_missing_tps.py --live --tp-only ETH_USDT DOT_USDT

  # If TP fails because SL locked the qty: cancel SL, place TP, recreate SL
  python3 scripts/recover_missing_tps.py --live --cancel-sl-first ETH_USDT DOT_USDT

  # Persist resolved entry into watchlist.purchase_price
  python3 scripts/recover_missing_tps.py --write-purchase-price AKT_USDT AAVE_USD
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.database import create_db_session
from app.models.exchange_order import ExchangeOrder, OrderSideEnum, OrderStatusEnum
from app.models.watchlist import WatchlistItem
from app.services.tp_sl_order_creator import create_stop_loss_order, create_take_profit_order
from app.utils.live_trading import get_live_trading_status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("recover_missing_tps")

# Symbols from the ATP Control Telegram alerts (2026-07-23)
DEFAULT_SYMBOLS = [
    "AKT_USDT",
    "AAVE_USD",
    "ATOM_USDT",
    "CRO_USDT",
    "LINK_USDT",
    "ETH_USDT",
    "DOT_USDT",
]

# Skip dust bags below this USD notional (position_qty * entry/mark)
DEFAULT_MIN_USD = 5.0

OPEN_STATUSES = [
    OrderStatusEnum.NEW,
    OrderStatusEnum.ACTIVE,
    OrderStatusEnum.PARTIALLY_FILLED,
]

PRIMARY_ORDER_TYPES = {"LIMIT", "MARKET", "LIMIT_MAKER"}


@dataclass
class EntryResolution:
    price: Optional[float] = None
    source: str = "none"
    parent_order_id: Optional[str] = None
    symbol_used: Optional[str] = None
    quantity_from_order: Optional[float] = None
    details: str = ""


@dataclass
class ProtectionState:
    active_sl: List[ExchangeOrder] = field(default_factory=list)
    active_tp: List[ExchangeOrder] = field(default_factory=list)
    rejected_tp: List[ExchangeOrder] = field(default_factory=list)


@dataclass
class SymbolPlan:
    symbol: str
    variants: List[str]
    base: str
    position_qty: Optional[float]
    entry: EntryResolution
    protection: ProtectionState
    watchlist: Optional[WatchlistItem]
    tp_price: Optional[float] = None
    sl_price: Optional[float] = None
    qty_to_use: Optional[float] = None
    action: str = "skip"
    notes: List[str] = field(default_factory=list)


def symbol_variants(symbol: str) -> List[str]:
    symbol = symbol.upper().strip()
    variants = [symbol]
    if "_" not in symbol:
        variants.extend([f"{symbol}_USDT", f"{symbol}_USD"])
    elif symbol.endswith("_USDT"):
        variants.append(symbol.replace("_USDT", "_USD"))
    elif symbol.endswith("_USD"):
        variants.append(symbol.replace("_USD", "_USDT"))
    # de-dupe preserving order
    seen = set()
    out = []
    for v in variants:
        if v not in seen:
            seen.add(v)
            out.append(v)
    return out


def base_currency(symbol: str) -> str:
    s = symbol.upper()
    return s.split("_")[0] if "_" in s else s


def _order_price(order: ExchangeOrder) -> Optional[float]:
    price = order.avg_price or order.price
    if (not price or float(price) <= 0) and getattr(order, "cumulative_value", None) and getattr(
        order, "cumulative_quantity", None
    ):
        cq = float(order.cumulative_quantity or 0)
        cv = float(order.cumulative_value or 0)
        if cq > 0 and cv > 0:
            price = cv / cq
    if price is None:
        return None
    try:
        p = float(price)
        return p if p > 0 else None
    except (TypeError, ValueError):
        return None


def _order_qty(order: ExchangeOrder) -> Optional[float]:
    raw = order.cumulative_quantity or order.quantity
    if raw is None:
        return None
    try:
        q = float(raw)
        return q if q > 0 else None
    except (TypeError, ValueError):
        return None


def resolve_entry_price(db, symbol: str, watchlist: Optional[WatchlistItem]) -> EntryResolution:
    variants = symbol_variants(symbol)

    buys = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(variants),
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
            ExchangeOrder.order_type.in_(list(PRIMARY_ORDER_TYPES)),
        )
        .order_by(ExchangeOrder.exchange_create_time.desc())
        .all()
    )

    # Prefer most recent fill with a usable price; fall back to any FILLED BUY
    if not buys:
        buys = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.symbol.in_(variants),
                ExchangeOrder.side == OrderSideEnum.BUY,
                ExchangeOrder.status == OrderStatusEnum.FILLED,
            )
            .order_by(ExchangeOrder.exchange_create_time.desc())
            .all()
        )

    for order in buys:
        price = _order_price(order)
        if price:
            return EntryResolution(
                price=price,
                source="filled_buy",
                parent_order_id=str(order.exchange_order_id),
                symbol_used=order.symbol,
                quantity_from_order=_order_qty(order),
                details=f"order={order.exchange_order_id} symbol={order.symbol}",
            )

    # Weighted avg of open lots (FIFO-ish) across variants if multiple buys exist
    all_buys = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(variants),
            ExchangeOrder.side == OrderSideEnum.BUY,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        )
        .order_by(ExchangeOrder.exchange_create_time.asc())
        .all()
    )
    sells = (
        db.query(ExchangeOrder)
        .filter(
            ExchangeOrder.symbol.in_(variants),
            ExchangeOrder.side == OrderSideEnum.SELL,
            ExchangeOrder.status == OrderStatusEnum.FILLED,
        )
        .order_by(ExchangeOrder.exchange_create_time.asc())
        .all()
    )
    sell_left = [Decimal(str(_order_qty(s) or 0)) for s in sells]
    open_notional = Decimal("0")
    open_qty = Decimal("0")
    last_open_order: Optional[ExchangeOrder] = None
    for buy in all_buys:
        bp = _order_price(buy)
        bq = _order_qty(buy)
        if not bp or not bq:
            continue
        remaining = Decimal(str(bq))
        for i, left in enumerate(sell_left):
            if remaining <= 0:
                break
            take = min(remaining, left)
            sell_left[i] = left - take
            remaining -= take
        if remaining > 0:
            open_notional += remaining * Decimal(str(bp))
            open_qty += remaining
            last_open_order = buy
    if open_qty > 0 and open_notional > 0:
        avg = float(open_notional / open_qty)
        return EntryResolution(
            price=avg,
            source="fifo_open_lots",
            parent_order_id=str(last_open_order.exchange_order_id) if last_open_order else None,
            symbol_used=last_open_order.symbol if last_open_order else symbol,
            quantity_from_order=float(open_qty),
            details=f"open_qty={float(open_qty):.8f}",
        )

    if watchlist:
        for attr, source in (("purchase_price", "watchlist.purchase_price"), ("price", "watchlist.price")):
            raw = getattr(watchlist, attr, None)
            if raw is not None and float(raw) > 0:
                return EntryResolution(
                    price=float(raw),
                    source=source,
                    symbol_used=watchlist.symbol,
                    details=f"watchlist_id={watchlist.id}",
                )

    # Market mark (correct fetcher API — sl_tp_checker imports a missing get_price)
    try:
        from simple_price_fetcher import price_fetcher

        for variant in variants:
            result = price_fetcher.get_price(variant)
            if result and result.success and result.price and result.price > 0:
                return EntryResolution(
                    price=float(result.price),
                    source=f"market:{result.source}",
                    symbol_used=variant,
                    details="WARNING: mark price, not true entry — TP/SL % will be relative to mark",
                )
    except Exception as exc:
        logger.warning("Market price fallback failed for %s: %s", symbol, exc)

    return EntryResolution(details="no filled BUY / purchase_price / market")


def get_position_qty(base: str) -> Optional[float]:
    """Return wallet balance for base currency (same shape as sl_tp_checker)."""
    try:
        from app.services.brokers.crypto_com_trade import trade_client

        summary = trade_client.get_account_summary()
        accounts = []
        if isinstance(summary, dict):
            accounts = summary.get("accounts") or []
            if not accounts:
                result = summary.get("result") or {}
                if isinstance(result, dict):
                    accounts = result.get("accounts") or []
        base_u = base.upper()
        for acct in accounts or []:
            if not isinstance(acct, dict):
                continue
            currency = str(acct.get("currency") or acct.get("instrument_name") or "").upper()
            if not currency:
                continue
            currency_base = currency.split("_")[0] if "_" in currency else currency
            if currency_base != base_u and currency != base_u:
                continue
            try:
                qty = float(acct.get("balance", 0) or 0)
            except (TypeError, ValueError):
                continue
            return qty if qty > 0 else 0.0
    except Exception as exc:
        logger.warning("Could not fetch account balance for %s: %s", base, exc)
    return None


def find_watchlist(db, symbol: str) -> Optional[WatchlistItem]:
    for variant in symbol_variants(symbol):
        item = (
            db.query(WatchlistItem)
            .filter(WatchlistItem.symbol == variant, WatchlistItem.is_deleted.is_(False))
            .first()
        )
        if item:
            return item
    base = base_currency(symbol)
    return (
        db.query(WatchlistItem)
        .filter(WatchlistItem.symbol == base, WatchlistItem.is_deleted.is_(False))
        .first()
    )


def protection_state(db, symbol: str, parent_order_id: Optional[str]) -> ProtectionState:
    variants = symbol_variants(symbol)
    q = db.query(ExchangeOrder).filter(ExchangeOrder.symbol.in_(variants))
    if parent_order_id:
        linked = q.filter(ExchangeOrder.parent_order_id == str(parent_order_id))
    else:
        linked = q

    active_sl = (
        linked.filter(
            ExchangeOrder.order_role == "STOP_LOSS",
            ExchangeOrder.status.in_(OPEN_STATUSES),
        ).all()
    )
    active_tp = (
        linked.filter(
            ExchangeOrder.order_role == "TAKE_PROFIT",
            ExchangeOrder.status.in_(OPEN_STATUSES),
        ).all()
    )
    rejected_tp = (
        linked.filter(
            ExchangeOrder.order_role == "TAKE_PROFIT",
            ExchangeOrder.status == OrderStatusEnum.REJECTED,
        )
        .order_by(ExchangeOrder.exchange_create_time.desc())
        .limit(5)
        .all()
    )

    # Also scan any open SL/TP on the symbol if parent link is missing
    if not active_sl and not active_tp:
        active_sl = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.symbol.in_(variants),
                ExchangeOrder.order_role == "STOP_LOSS",
                ExchangeOrder.status.in_(OPEN_STATUSES),
            )
            .all()
        )
        active_tp = (
            db.query(ExchangeOrder)
            .filter(
                ExchangeOrder.symbol.in_(variants),
                ExchangeOrder.order_role == "TAKE_PROFIT",
                ExchangeOrder.status.in_(OPEN_STATUSES),
            )
            .all()
        )

    return ProtectionState(active_sl=active_sl, active_tp=active_tp, rejected_tp=rejected_tp)


def calc_levels(
    entry: float,
    watchlist: Optional[WatchlistItem],
) -> Tuple[float, float, float, float]:
    mode = ((watchlist.sl_tp_mode if watchlist else None) or "conservative").lower()
    default_sl, default_tp = (2.0, 2.0) if mode == "aggressive" else (3.0, 3.0)
    sl_pct = abs(float(watchlist.sl_percentage)) if watchlist and watchlist.sl_percentage else default_sl
    tp_pct = abs(float(watchlist.tp_percentage)) if watchlist and watchlist.tp_percentage else default_tp

    if watchlist and watchlist.sl_price and float(watchlist.sl_price) > 0:
        sl_price = float(watchlist.sl_price)
    else:
        sl_price = entry * (1 - sl_pct / 100)

    if watchlist and watchlist.tp_price and float(watchlist.tp_price) > 0:
        tp_price = float(watchlist.tp_price)
    else:
        tp_price = entry * (1 + tp_pct / 100)

    # Round similarly to create_missing_tp_orders
    if entry >= 100:
        sl_price, tp_price = round(sl_price), round(tp_price)
    else:
        sl_price, tp_price = round(sl_price, 4), round(tp_price, 4)

    return sl_price, tp_price, sl_pct, tp_pct


def build_plan(db, symbol: str, min_usd: float = DEFAULT_MIN_USD) -> SymbolPlan:
    variants = symbol_variants(symbol)
    base = base_currency(symbol)
    watchlist = find_watchlist(db, symbol)
    entry = resolve_entry_price(db, symbol, watchlist)
    pos_qty = get_position_qty(base)
    protection = protection_state(db, symbol, entry.parent_order_id)

    plan = SymbolPlan(
        symbol=symbol,
        variants=variants,
        base=base,
        position_qty=pos_qty,
        entry=entry,
        protection=protection,
        watchlist=watchlist,
    )

    qty = None
    if pos_qty is not None and pos_qty > 0:
        qty = pos_qty
        plan.notes.append(f"qty from account balance={pos_qty}")
    elif entry.quantity_from_order:
        qty = entry.quantity_from_order
        plan.notes.append(f"qty from entry order={qty}")
    plan.qty_to_use = qty

    if pos_qty is not None and pos_qty <= 0:
        plan.action = "skip_no_position"
        plan.notes.append("account balance is 0")
        return plan

    if not entry.price:
        plan.action = "need_manual_entry"
        plan.notes.append("could not resolve entry price")
        return plan

    # Dust filter: skip tiny notionals (AKT/ATOM/CRO/LINK dust, etc.)
    notional = float(qty or 0) * float(entry.price)
    plan.notes.append(f"notional≈${notional:.4f}")
    if notional < float(min_usd):
        plan.action = "skip_dust"
        plan.notes.append(f"below min_usd=${min_usd}")
        return plan

    sl_price, tp_price, sl_pct, tp_pct = calc_levels(entry.price, watchlist)
    plan.sl_price = sl_price
    plan.tp_price = tp_price
    plan.notes.append(f"levels sl={sl_pct}% tp={tp_pct}%")

    has_sl = bool(protection.active_sl)
    has_tp = bool(protection.active_tp)

    if has_sl and has_tp:
        plan.action = "ok_protected"
    elif has_tp and not has_sl:
        plan.action = "create_sl"
    elif has_sl and not has_tp:
        plan.action = "create_tp"
        if protection.rejected_tp:
            plan.notes.append(
                f"{len(protection.rejected_tp)} REJECTED TP(s) — may need --cancel-sl-first"
            )
    else:
        plan.action = "create_sl_tp"

    if qty is None or qty <= 0:
        plan.notes.append("WARNING: no quantity resolved — cannot place without --qty")
        if plan.action.startswith("create"):
            plan.action = "need_qty"

    return plan


def cancel_orders(order_ids: Sequence[str], dry_run: bool) -> List[str]:
    cancelled = []
    from app.services.brokers.crypto_com_trade import trade_client

    for oid in order_ids:
        if dry_run:
            logger.info("[DRY-RUN] would cancel order %s", oid)
            cancelled.append(oid)
            continue
        try:
            result = trade_client.cancel_order(str(oid))
            logger.info("Cancel %s -> %s", oid, result)
            cancelled.append(oid)
        except Exception as exc:
            logger.error("Failed to cancel %s: %s", oid, exc)
    return cancelled


def place_protection(
    db,
    plan: SymbolPlan,
    *,
    live: bool,
    tp_only: bool,
    cancel_sl_first: bool,
) -> Dict[str, Any]:
    dry_run = not live
    symbol = plan.symbol
    entry = plan.entry
    qty = plan.qty_to_use
    result: Dict[str, Any] = {"symbol": symbol, "placed": [], "errors": []}

    if qty is None or qty <= 0 or not entry.price or not plan.tp_price:
        result["errors"].append("missing qty/entry/tp_price")
        return result

    # Prefer the symbol that actually traded (USD vs USDT)
    place_symbol = entry.symbol_used or symbol
    parent_id = entry.parent_order_id
    oco = None
    if plan.protection.active_sl:
        oco = plan.protection.active_sl[0].oco_group_id

    is_margin = bool(plan.watchlist and plan.watchlist.trade_on_margin)
    leverage = None
    if plan.watchlist and getattr(plan.watchlist, "leverage", None):
        try:
            leverage = float(plan.watchlist.leverage)
        except (TypeError, ValueError):
            leverage = None

    if cancel_sl_first and plan.protection.active_sl and plan.action in ("create_tp", "create_sl_tp"):
        sl_ids = [str(o.exchange_order_id) for o in plan.protection.active_sl if o.exchange_order_id]
        result["cancelled_sl"] = cancel_orders(sl_ids, dry_run=dry_run)
        # After cancelling SL we will recreate both unless tp_only
        if not tp_only:
            plan.action = "create_sl_tp"
        else:
            plan.action = "create_tp"

    want_tp = plan.action in ("create_tp", "create_sl_tp") or (
        cancel_sl_first and plan.action == "create_tp"
    )
    want_sl = (not tp_only) and plan.action in ("create_sl", "create_sl_tp")

    if want_tp:
        logger.info(
            "%s TP %s qty=%s entry=%s tp=%s margin=%s parent=%s",
            "[DRY-RUN]" if dry_run else "[LIVE]",
            place_symbol,
            qty,
            entry.price,
            plan.tp_price,
            is_margin,
            parent_id,
        )
        tp_res = create_take_profit_order(
            db=db,
            symbol=place_symbol,
            side="BUY",
            tp_price=float(plan.tp_price),
            quantity=float(qty),
            entry_price=float(entry.price),
            parent_order_id=parent_id,
            oco_group_id=oco,
            is_margin=is_margin,
            leverage=leverage,
            dry_run=dry_run,
            source="manual",
        )
        if tp_res.get("order_id"):
            result["placed"].append({"role": "TAKE_PROFIT", "order_id": tp_res["order_id"]})
            oco = oco or tp_res.get("oco_group_id")
        else:
            result["errors"].append(f"TP: {tp_res.get('error') or tp_res}")

    if want_sl and plan.sl_price:
        logger.info(
            "%s SL %s qty=%s entry=%s sl=%s margin=%s parent=%s",
            "[DRY-RUN]" if dry_run else "[LIVE]",
            place_symbol,
            qty,
            entry.price,
            plan.sl_price,
            is_margin,
            parent_id,
        )
        sl_res = create_stop_loss_order(
            db=db,
            symbol=place_symbol,
            side="BUY",
            sl_price=float(plan.sl_price),
            quantity=float(qty),
            entry_price=float(entry.price),
            parent_order_id=parent_id,
            oco_group_id=oco,
            is_margin=is_margin,
            leverage=leverage,
            dry_run=dry_run,
            source="manual",
        )
        if sl_res.get("order_id"):
            result["placed"].append({"role": "STOP_LOSS", "order_id": sl_res["order_id"]})
        else:
            result["errors"].append(f"SL: {sl_res.get('error') or sl_res}")

    return result


def print_plan(plan: SymbolPlan) -> None:
    print("\n" + "=" * 72)
    print(f"SYMBOL: {plan.symbol}  (variants: {', '.join(plan.variants)})")
    print(f"  base={plan.base}  position_qty={plan.position_qty}")
    wl = plan.watchlist
    if wl:
        print(
            f"  watchlist: {wl.symbol} margin={bool(wl.trade_on_margin)} "
            f"purchase_price={wl.purchase_price} tp%={wl.tp_percentage} sl%={wl.sl_percentage}"
        )
    else:
        print("  watchlist: (none)")
    e = plan.entry
    print(f"  entry: {e.price}  source={e.source}  {e.details}")
    if e.parent_order_id:
        print(f"  parent_order_id: {e.parent_order_id} ({e.symbol_used})")
    print(f"  active SL: {len(plan.protection.active_sl)}  active TP: {len(plan.protection.active_tp)}")
    for sl in plan.protection.active_sl[:3]:
        print(f"    SL {sl.exchange_order_id} status={sl.status} qty={sl.quantity}")
    for tp in plan.protection.active_tp[:3]:
        print(f"    TP {tp.exchange_order_id} status={tp.status} qty={tp.quantity}")
    for rtp in plan.protection.rejected_tp[:2]:
        print(f"    REJECTED TP {rtp.exchange_order_id}")
    print(f"  planned qty={plan.qty_to_use}  sl={plan.sl_price}  tp={plan.tp_price}")
    print(f"  ACTION: {plan.action}")
    for n in plan.notes:
        print(f"  note: {n}")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Recover missing TP/SL with better entry-price resolution")
    p.add_argument("symbols", nargs="*", help="Symbols to process (default: alert set)")
    p.add_argument("--live", action="store_true", help="Actually place orders (default: dry-run)")
    p.add_argument("--tp-only", action="store_true", help="Only create missing TPs (not SLs)")
    p.add_argument(
        "--cancel-sl-first",
        action="store_true",
        help="Cancel active SL before placing TP (workaround for INSUFFICIENT_ACC_BALANCE lock)",
    )
    p.add_argument(
        "--write-purchase-price",
        action="store_true",
        help="Write resolved entry into watchlist.purchase_price when missing",
    )
    p.add_argument("--qty", type=float, default=None, help="Force quantity for all symbols")
    p.add_argument(
        "--entry",
        type=float,
        default=None,
        help="Force entry price for all symbols (ops override)",
    )
    p.add_argument(
        "--min-usd",
        type=float,
        default=DEFAULT_MIN_USD,
        help=f"Skip dust positions below this USD notional (default {DEFAULT_MIN_USD})",
    )
    return p.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    symbols = [s.upper() for s in (args.symbols or DEFAULT_SYMBOLS)]
    live_flag = bool(args.live)

    db = create_db_session()
    try:
        live_trading = get_live_trading_status(db)
        print(f"Mode: {'LIVE' if live_flag else 'DRY-RUN'} | LIVE_TRADING setting={live_trading}")
        print(f"Symbols: {', '.join(symbols)}")
        print(f"Started: {datetime.now(timezone.utc).isoformat()}")

        if live_flag and not live_trading:
            print("\nREFUSING --live because LIVE_TRADING is false. Enable it first.")
            return 2

        plans: List[SymbolPlan] = []
        for symbol in symbols:
            plan = build_plan(db, symbol, min_usd=args.min_usd)
            if args.qty is not None and args.qty > 0:
                plan.qty_to_use = args.qty
                if plan.action in ("need_qty",):
                    # re-evaluate action roughly
                    has_sl = bool(plan.protection.active_sl)
                    has_tp = bool(plan.protection.active_tp)
                    if has_sl and not has_tp:
                        plan.action = "create_tp"
                    elif not has_sl and not has_tp:
                        plan.action = "create_sl_tp"
                    elif not has_sl and has_tp:
                        plan.action = "create_sl"
            if args.entry is not None and args.entry > 0:
                plan.entry = EntryResolution(
                    price=args.entry,
                    source="cli --entry",
                    parent_order_id=plan.entry.parent_order_id,
                    symbol_used=plan.entry.symbol_used or symbol,
                    quantity_from_order=plan.entry.quantity_from_order,
                )
                sl_price, tp_price, _, _ = calc_levels(args.entry, plan.watchlist)
                plan.sl_price = sl_price
                plan.tp_price = tp_price
                if plan.action == "need_manual_entry":
                    has_sl = bool(plan.protection.active_sl)
                    has_tp = bool(plan.protection.active_tp)
                    if plan.qty_to_use and plan.qty_to_use > 0:
                        if has_sl and not has_tp:
                            plan.action = "create_tp"
                        elif not has_sl and not has_tp:
                            plan.action = "create_sl_tp"
                        elif not has_sl and has_tp:
                            plan.action = "create_sl"
            print_plan(plan)
            plans.append(plan)

            if args.write_purchase_price and plan.entry.price and plan.watchlist:
                if not plan.watchlist.purchase_price:
                    if live_flag:
                        plan.watchlist.purchase_price = float(plan.entry.price)
                        db.commit()
                        print(f"  wrote purchase_price={plan.entry.price}")
                    else:
                        print(f"  [DRY-RUN] would write purchase_price={plan.entry.price}")

        actionable = [p for p in plans if p.action.startswith("create")]
        print("\n" + "=" * 72)
        print(f"Summary: {len(plans)} symbols | actionable={len(actionable)}")
        for p in plans:
            print(f"  {p.symbol:12} {p.action:20} entry={p.entry.price} src={p.entry.source}")

        if not actionable:
            print("\nNothing to place.")
            return 0

        if not live_flag:
            print("\nDry-run only. Re-run with --live to place orders.")
            print("For ETH/DOT INSUFFICIENT_ACC_BALANCE, try: --live --cancel-sl-first --tp-only")
            return 0

        print("\nPlacing protection orders...")
        failures = 0
        for plan in actionable:
            res = place_protection(
                db,
                plan,
                live=True,
                tp_only=args.tp_only,
                cancel_sl_first=args.cancel_sl_first,
            )
            print(f"  {plan.symbol}: placed={res.get('placed')} errors={res.get('errors')}")
            if res.get("errors"):
                failures += 1
        return 1 if failures else 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
