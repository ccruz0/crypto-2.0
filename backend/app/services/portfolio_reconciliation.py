"""Helpers to reconcile live Crypto.com balances with cached portfolio data."""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Dict, List, Tuple

from sqlalchemy.orm import Session

from app.models.portfolio import PortfolioBalance
from app.services.brokers.crypto_com_trade import trade_client
from app.services.portfolio_cache import _normalize_currency_name

logger = logging.getLogger(__name__)

RECON_TOLERANCE = 1e-8


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _collect_live_balances() -> Tuple[Dict[str, float], Dict[str, List[str]]]:
    """Return aggregated live balances (normalized) and the account types they came from."""
    summary = trade_client.get_account_summary() or {}
    accounts = summary.get("accounts") or []

    totals: Dict[str, float] = defaultdict(float)
    account_types: Dict[str, set] = defaultdict(set)

    for account in accounts:
        raw_symbol = (
            account.get("currency")
            or account.get("instrument_name")
            or account.get("symbol")
        )
        symbol = _normalize_currency_name(raw_symbol)
        if not symbol:
            continue

        quantity = (
            account.get("balance")
            or account.get("quantity")
            or account.get("available")
        )
        qty_value = _to_float(quantity)
        if qty_value <= 0:
            continue

        totals[symbol] += qty_value

        account_type = (
            account.get("account_type")
            or account.get("type")
            or account.get("account_name")
            or "UNKNOWN"
        )
        account_types[symbol].add(str(account_type).upper())

    return totals, {sym: sorted(types) for sym, types in account_types.items()}


def _collect_cached_balances(db: Session) -> Dict[str, float]:
    """Return aggregated cached balances by normalized currency."""
    cached_totals: Dict[str, float] = defaultdict(float)
    rows = db.query(PortfolioBalance.currency, PortfolioBalance.balance).all()
    for currency, balance in rows:
        symbol = _normalize_currency_name(currency)
        if not symbol:
            continue
        cached_totals[symbol] += _to_float(balance)
    return cached_totals


def reconcile_portfolio_balances(db: Session, tolerance: float = RECON_TOLERANCE) -> Dict:
    """
    Compare live Crypto.com balances vs cached portfolio balances.
    Returns structured differences to help diagnose missing assets.
    """
    live_balances, live_sources = _collect_live_balances()
    cached_balances = _collect_cached_balances(db)

    live_symbols = set(live_balances.keys())
    cached_symbols = set(cached_balances.keys())

    missing_in_portfolio = [
        {
            "symbol": symbol,
            "live_qty": live_balances[symbol],
            "accounts": live_sources.get(symbol, []),
        }
        for symbol in sorted(live_symbols - cached_symbols)
    ]

    missing_in_live = [
        {
            "symbol": symbol,
            "cached_qty": cached_balances[symbol],
        }
        for symbol in sorted(cached_symbols - live_symbols)
    ]

    mismatched_quantities = []
    for symbol in sorted(live_symbols & cached_symbols):
        live_qty = live_balances[symbol]
        cache_qty = cached_balances[symbol]
        delta = live_qty - cache_qty
        if abs(delta) > tolerance:
            mismatched_quantities.append(
                {
                    "symbol": symbol,
                    "live_qty": live_qty,
                    "cache_qty": cache_qty,
                    "delta": delta,
                }
            )

    report = {
        "missing_in_portfolio": missing_in_portfolio,
        "missing_in_live": missing_in_live,
        "mismatched_quantities": mismatched_quantities,
        "live_total_symbols": len(live_symbols),
        "cached_total_symbols": len(cached_symbols),
    }

    logger.info(
        "Portfolio reconciliation: %s missing_in_portfolio=%d missing_in_live=%d mismatches=%d",
        ", ".join(sorted(live_symbols)),
        len(missing_in_portfolio),
        len(missing_in_live),
        len(mismatched_quantities),
    )

    return report



