"""Shadow counter for open positions — measures, never decides (PASO B1).

Why this exists
---------------
Two accountings disagree about how many positions are open, and the guards
consume the wrong one.

``order_position_service.count_open_positions_for_symbol`` subtracts aggregates:

    long_net_qty = max(filled_buy_qty - filled_long_close_sell_qty, 0.0)

That has three defects, all measured in production on 2026-08-20 (#523):

1. **Every close counts twice.** One physical protection fill lands as two rows
   — the trigger id and its spot remap. ALGO's stop of 1149 appears as
   ``73817490102095276`` and ``5755600493106121990``, same quantity, same
   second. Raw close totals run ~2x high across the book.
2. **The populations are asymmetric.** Entries require ``trade_signal_id IS NOT
   NULL`` (bot only); closes require nothing (bot, manual and exchange-synced).
   Narrow numerator, wide subtrahend.
3. **Nothing is paired.** A close belonging to parent X reduces parent Y.

None of the three decays — neither term has a time window — so the subtrahend
grows without bound and the result sits pinned at 0. In production it reported
1 open position against 8 real ones, which is why ``maxOpenOrdersPerCoin`` and
``maxOpenOrdersTotal`` stopped limiting anything.

``expected_take_profit.rebuild_open_lots`` already gets this right: it settles
``parent_order_id`` closes before FIFO, collapses the twin fills, and aligns the
result to the wallet. This module reuses it rather than adding a third
accounting — a fixed-but-different subtraction would just create two truths.

What this module does NOT do
----------------------------
It decides nothing. Every guard keeps using the legacy count; this only records
what the new one would have said, what it cost, and where the two disagree. The
switch is PASO B2, and it lands only once the shadow data meets the exit
criterion in ``docs/project-history/``.

Consequently a wallet read failure here is logged and never blocks. Fail-closed
semantics belong to B2, where the number actually gates an order.
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Dict, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# Shadow work is pure overhead on the order path. One switch turns it off
# without a deploy if it ever costs more than it teaches.
SHADOW_ENABLED = lambda: (  # noqa: E731
    os.getenv("POSITION_COUNT_SHADOW_ENABLED", "true") or "true"
).strip().lower() in ("1", "true", "yes")

# The wallet snapshot is one exchange round-trip. The guard runs per entry
# attempt per symbol, so re-fetching per call would dominate the measurement.
# Shadow numbers tolerate a slightly stale wallet; the decision path in B2
# will not, and must resolve its own freshness policy.
WALLET_TTL_SECONDS = lambda: float(os.getenv("POSITION_COUNT_SHADOW_WALLET_TTL", "60"))  # noqa: E731

_wallet_cache: Dict[str, Decimal] = {}
_wallet_cache_at: float = 0.0
_wallet_cache_ok: bool = False


def _base_of(symbol: str) -> str:
    symbol = (symbol or "").upper()
    return symbol.split("_")[0] if "_" in symbol else symbol


def _load_wallet_by_base(force: bool = False) -> Tuple[Dict[str, Decimal], bool]:
    """Wallet balances per base asset, TTL-cached. Returns (balances, ok)."""
    global _wallet_cache, _wallet_cache_at, _wallet_cache_ok

    now = time.time()
    if not force and _wallet_cache_ok and (now - _wallet_cache_at) < WALLET_TTL_SECONDS():
        return _wallet_cache, True

    try:
        from app.services.brokers.crypto_com_trade import trade_client

        summary = trade_client.get_account_summary()
        accounts = (summary or {}).get("accounts") or []
        balances: Dict[str, Decimal] = {}
        for account in accounts:
            currency = str(account.get("currency") or "").upper()
            if not currency:
                continue
            raw = account.get("balance", account.get("quantity", 0))
            try:
                balances[currency] = balances.get(currency, Decimal(0)) + Decimal(str(raw or 0))
            except Exception:
                continue
        if not balances:
            return _wallet_cache, False
        _wallet_cache = balances
        _wallet_cache_at = now
        _wallet_cache_ok = True
        return balances, True
    except Exception as e:
        logger.debug("[POSITION_COUNT_SHADOW] wallet read failed: %s", e)
        # Stale is better than nothing for a measurement, but say which it was.
        return _wallet_cache, False


def _cap_lots_to_wallet_for_count(
    db: Session,
    lots: list,
    wallet_abs: Decimal,
) -> Tuple[list, int]:
    """Cap the COUNTED lot quantity at |wallet|. Returns (kept, ghosts_dropped).

    The rule itself now lives in ``expected_take_profit.split_lots_by_wallet_capacity``
    so the counter and the display classify lots identically instead of keeping
    two copies that could drift. Behaviour here is unchanged: protected lots are
    never dropped (they are the live position), unprotected lots are kept
    newest-first while the running total fits in |wallet| plus dust, and old
    naked leftovers — the ghost signature — fall off first.

    Origin (measured 28-ago-2026 on APT): protected 173.10 + naked ghosts 17.65
    + 17.54, entries of 2-3 ago whose protections were all cancelled on 11-ago,
    = 208.29 counted vs wallet 173.49 — count said 3, truth was 1.

    The difference is what each caller does with the lots that do not fit: the
    counter drops them, the display keeps them visible (a real fill whose SL/TP
    failed must stay on screen) but excludes them from every quantity aggregate.
    """
    from app.services.expected_take_profit import split_lots_by_wallet_capacity

    kept, exceeding = split_lots_by_wallet_capacity(db, lots, wallet_abs)
    return kept, len(exceeding)


def count_open_lots_for_symbol(
    db: Session,
    symbol: str,
    *,
    wallet_by_base: Optional[Dict[str, Decimal]] = None,
) -> dict:
    """Open positions for a base asset, counted off the FIFO lots.

    Returns a dict with the count and the evidence behind it, so a divergence
    can be explained from the log line alone without re-running anything.
    """
    from app.services.expected_take_profit import (
        _align_open_lots_to_wallet,
        rebuild_open_lots,
    )

    base = _base_of(symbol)
    lots = rebuild_open_lots(db, base) or []
    raw_lots = len(lots)

    if wallet_by_base is None:
        wallet_by_base, wallet_ok = _load_wallet_by_base()
    else:
        wallet_ok = True

    wallet_balance = Decimal(str(wallet_by_base.get(base, 0) or 0))
    aligned = False
    warning = None
    if wallet_ok:
        try:
            lots, warning = _align_open_lots_to_wallet(db, lots, wallet_balance)
            lots = lots or []
            aligned = True
        except Exception as e:
            logger.debug("[POSITION_COUNT_SHADOW] wallet alignment failed for %s: %s", base, e)

    ghosts_dropped = 0
    if wallet_ok:
        lots, ghosts_dropped = _cap_lots_to_wallet_for_count(
            db, lots or [], abs(wallet_balance)
        )

    long_qty = Decimal(0)
    short_qty = Decimal(0)
    for lot in lots:
        qty = Decimal(str(getattr(lot, "lot_qty", 0) or 0))
        if _lot_is_short(db, lot):
            short_qty += abs(qty)
        else:
            long_qty += abs(qty)

    return {
        "base": base,
        "count": len(lots),
        "lots_before_wallet": raw_lots,
        "ghosts_dropped": ghosts_dropped,
        "long_qty": float(long_qty),
        "short_qty": float(short_qty),
        "wallet": float(wallet_balance),
        "wallet_ok": wallet_ok,
        "aligned": aligned,
        "warning": warning,
    }


def _lot_is_short(db: Session, lot) -> bool:
    from app.models.exchange_order import OrderSideEnum

    try:
        from app.services.expected_take_profit import _entry_side_for_lot

        return _entry_side_for_lot(db, lot) == OrderSideEnum.SELL
    except Exception:
        return getattr(lot, "entry_side", None) == OrderSideEnum.SELL


def record_shadow_count(db: Session, symbol: str, legacy_count: int) -> None:
    """Compute the lot-based count next to the legacy one and log both.

    Never raises and never returns a value: callers must not be able to make a
    decision out of this, by construction.
    """
    if not SHADOW_ENABLED():
        return

    started = time.perf_counter()
    try:
        result = count_open_lots_for_symbol(db, symbol)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        diverges = int(result["count"] != legacy_count)
        # One line, fixed keys, so a shadow window can be aggregated with grep
        # and awk instead of a bespoke parser.
        logger.info(
            "[POSITION_COUNT_SHADOW] symbol=%s base=%s legacy=%d shadow=%d diverge=%d "
            "long_qty=%.8f short_qty=%.8f wallet=%.8f wallet_ok=%d aligned=%d "
            "lots_pre=%d ghosts_dropped=%d ms=%.1f warning=%s",
            (symbol or "").upper(),
            result["base"],
            legacy_count,
            result["count"],
            diverges,
            result["long_qty"],
            result["short_qty"],
            result["wallet"],
            int(result["wallet_ok"]),
            int(result["aligned"]),
            result["lots_before_wallet"],
            result.get("ghosts_dropped", 0),
            elapsed_ms,
            result["warning"] or "-",
        )
    except Exception as e:
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        # A shadow that dies quietly would read as "no divergence".
        logger.warning(
            "[POSITION_COUNT_SHADOW] symbol=%s legacy=%d shadow=ERROR ms=%.1f error=%s",
            (symbol or "").upper(),
            legacy_count,
            elapsed_ms,
            e,
        )
