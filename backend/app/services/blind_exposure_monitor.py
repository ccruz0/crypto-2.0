"""Blind exposure: money the legacy position counter cannot see.

Measured in production on 2026-09-05: 12 of 22 symbols report a legacy count of
zero while real lots exist behind them. Root cause is documented in
`docs/project-history/contador-medicion-2026-09-05.md`: the numerator of the
legacy counter requires `trade_signal_id IS NOT NULL`
(`_bot_main_entry_filter`), and `trade_signals` stopped being written in July --
2 rows in the last 30 days against 130 executed entries. With an empty
numerator, `max(0 - closes, 0) = 0` for any number of closes.

The exposure was $111.41 on a $48,412 equity (0.23%) and is not growing
(+$0.18/day), but nothing watches it. This module is that watchdog. It does not
fix the counter and must never be used to make a trading decision: it only
measures and exports.

Dust is excluded on purpose. Eleven of the twelve divergences are sub-$5
remainders left by deliberate policy (`SYSTEM_CORE_MIN_POSITION_USD`), so
counting them would drown the one symbol that matters -- DOGE, at $97.90.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, List

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)


def _dust_usd() -> float:
    """Same floor the trade guards use, read the same way."""
    try:
        return float(os.getenv("SYSTEM_CORE_MIN_POSITION_USD", "5") or 5.0)
    except Exception:
        return 5.0


def _price_for(db: Session, symbol: str) -> float:
    """Last known price, or 0.0 when unknown (symbol then contributes nothing)."""
    try:
        from app.models.market_price import MarketPrice

        row = (
            db.query(MarketPrice)
            .filter(MarketPrice.symbol == symbol)
            .order_by(MarketPrice.updated_at.desc())
            .first()
        )
        return float(row.price) if row is not None and row.price else 0.0
    except Exception as e:
        logger.debug("[BLIND_EXPOSURE] price lookup failed for %s: %s", symbol, e)
        return 0.0


def collect_blind_exposure(db: Session) -> Dict[str, Any]:
    """Value, in USD, of positions the legacy counter reports as zero.

    Never raises. A watchdog that dies quietly would read as "no exposure",
    which is the failure mode this module exists to prevent, so every failure
    is counted and surfaced in `errors`.
    """
    stats: Dict[str, Any] = {
        "total_usd": 0.0,
        "symbols_total": 0,
        "max_symbol_usd": 0.0,
        "max_symbol": "",
        "errors": 0,
        "checked": 0,
        "details": [],
    }

    try:
        from app.models.watchlist import WatchlistItem
        from app.services.order_position_service import count_open_positions_for_symbol
        from app.services.position_count_shadow import count_open_lots_for_symbol
        from app.services.system_core_trade_guards import _position_dust_kwargs
    except Exception as e:
        logger.warning("[BLIND_EXPOSURE] imports failed: %s", e)
        stats["errors"] += 1
        return stats

    dust = _dust_usd()

    try:
        symbols = [
            s[0]
            for s in db.query(WatchlistItem.symbol).distinct().all()
            if s and s[0]
        ]
    except Exception as e:
        logger.warning("[BLIND_EXPOSURE] watchlist read failed: %s", e)
        stats["errors"] += 1
        return stats

    details: List[Dict[str, Any]] = []

    for symbol in symbols:
        try:
            price = _price_for(db, symbol)
            legacy = int(
                count_open_positions_for_symbol(
                    db, symbol, **_position_dust_kwargs(price or None)
                )
            )
            if legacy > 0:
                stats["checked"] += 1
                continue

            shadow = count_open_lots_for_symbol(db, symbol)
            qty = float(shadow.get("long_qty") or 0.0) + float(
                shadow.get("short_qty") or 0.0
            )
            usd = qty * price
            stats["checked"] += 1

            if usd < dust:
                continue

            details.append(
                {
                    "symbol": symbol,
                    "usd": round(usd, 2),
                    "qty": qty,
                    "price": price,
                    "shadow_count": int(shadow.get("count") or 0),
                }
            )
            stats["total_usd"] += usd
            stats["symbols_total"] += 1
            if usd > stats["max_symbol_usd"]:
                stats["max_symbol_usd"] = usd
                stats["max_symbol"] = symbol
        except Exception as e:
            stats["errors"] += 1
            logger.debug("[BLIND_EXPOSURE] symbol %s failed: %s", symbol, e)

    stats["total_usd"] = round(stats["total_usd"], 2)
    stats["max_symbol_usd"] = round(stats["max_symbol_usd"], 2)
    stats["details"] = sorted(details, key=lambda d: d["usd"], reverse=True)
    return stats


try:
    from prometheus_client import Gauge  # pyright: ignore[reportMissingImports]

    _blind_exposure_usd_total = Gauge(
        "blind_exposure_usd_total",
        "USD value of open positions the legacy counter reports as zero (dust excluded)",
    )
    _blind_exposure_symbols_total = Gauge(
        "blind_exposure_symbols_total",
        "Number of symbols with non-dust exposure invisible to the legacy counter",
    )
    _blind_exposure_max_symbol_usd = Gauge(
        "blind_exposure_max_symbol_usd",
        "Largest single-symbol exposure invisible to the legacy counter, in USD",
    )
    _blind_exposure_errors_total = Gauge(
        "blind_exposure_errors_total",
        "Symbols the blind-exposure watchdog could not evaluate in its last run",
    )
    _PROMETHEUS_AVAILABLE = True
except Exception:
    _blind_exposure_usd_total = None
    _blind_exposure_symbols_total = None
    _blind_exposure_max_symbol_usd = None
    _blind_exposure_errors_total = None
    _PROMETHEUS_AVAILABLE = False


def refresh_blind_exposure_metrics(db: Session) -> Dict[str, Any]:
    """Update the gauges and return the stats. Never raises."""
    stats = collect_blind_exposure(db)

    if _PROMETHEUS_AVAILABLE:
        try:
            if _blind_exposure_usd_total is not None:
                _blind_exposure_usd_total.set(stats["total_usd"])
            if _blind_exposure_symbols_total is not None:
                _blind_exposure_symbols_total.set(stats["symbols_total"])
            if _blind_exposure_max_symbol_usd is not None:
                _blind_exposure_max_symbol_usd.set(stats["max_symbol_usd"])
            if _blind_exposure_errors_total is not None:
                _blind_exposure_errors_total.set(stats["errors"])
        except Exception as e:
            logger.warning("[BLIND_EXPOSURE] gauge update failed: %s", e)

    # One line, fixed keys, so a window can be read with grep and awk. Kept at
    # INFO even when zero: silence must mean "the watchdog ran and saw nothing",
    # never "the watchdog is dead".
    logger.info(
        "[BLIND_EXPOSURE] total_usd=%.2f symbols=%d max_symbol=%s max_usd=%.2f "
        "checked=%d errors=%d top=%s",
        stats["total_usd"],
        stats["symbols_total"],
        stats["max_symbol"] or "-",
        stats["max_symbol_usd"],
        stats["checked"],
        stats["errors"],
        ",".join(f"{d['symbol']}:{d['usd']}" for d in stats["details"][:5]) or "-",
    )
    return stats
