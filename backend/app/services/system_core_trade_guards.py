"""
SYSTEM_CORE.md execution gates (optional; on by default).

Applied at BUY order placement in addition to existing signal/strategy logic.
Disable with SYSTEM_CORE_GUARDS_ENABLED=false.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Tuple

from sqlalchemy import func, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_MAX_PER_TRADE = float(os.getenv("SYSTEM_CORE_MAX_TRADE_USD", "1000"))
_MAX_DRAWDOWN_PCT = float(os.getenv("SYSTEM_CORE_MAX_DRAWDOWN_PCT", "5"))
_STATE_PATH = os.getenv("SYSTEM_CORE_EQUITY_STATE_PATH", "/tmp/system_core_equity_state.json")
_GUARDS_ON = (os.getenv("SYSTEM_CORE_GUARDS_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off"))
# If peak exceeds current equity by this factor, treat peak as stale (e.g. gross double-count) and rebaseline.
_STALE_PEAK_RATIO = float(os.getenv("SYSTEM_CORE_STALE_PEAK_RATIO", "1.75"))
# RSI buy gate: block when rsi >= this value. Default 40 (legacy). Aggressive strategy uses buyBelow 50 —
# set SYSTEM_CORE_RSI_BUY_MAX=50 on prod to align with scalp/aggressive profiles.
_RSI_BUY_MAX = float(os.getenv("SYSTEM_CORE_RSI_BUY_MAX", "40"))
# Dust: net filled remnant below these thresholds does not count as an open position for one-per-coin.
_MIN_POSITION_QTY = float(os.getenv("SYSTEM_CORE_MIN_POSITION_QTY", "0"))
_MIN_POSITION_USD = float(os.getenv("SYSTEM_CORE_MIN_POSITION_USD", "5"))


def system_core_guards_enabled() -> bool:
    return _GUARDS_ON


def _resolve_max_open_trades() -> int:
    """Max distinct symbols with open positions. Config -> SYSTEM_CORE_MAX_OPEN_TRADES -> 5."""
    try:
        from app.services.config_loader import get_trading_limits

        return get_trading_limits()["maxOpenOrdersTotal"]
    except Exception as e:
        logger.debug("system_core: resolve max open trades from config failed: %s", e)
        return int(os.getenv("SYSTEM_CORE_MAX_OPEN_TRADES", "5"))


def _resolve_max_open_per_coin() -> int:
    """Max open positions per coin. Config -> SYSTEM_CORE_MAX_OPEN_PER_COIN -> 1."""
    try:
        from app.services.config_loader import get_trading_limits

        return get_trading_limits()["maxOpenOrdersPerCoin"]
    except Exception as e:
        logger.debug("system_core: resolve max open per coin from config failed: %s", e)
        return int(os.getenv("SYSTEM_CORE_MAX_OPEN_PER_COIN", "1"))


def _position_dust_kwargs(last_price: float | None = None) -> dict[str, float | None]:
    return {
        "min_position_qty": _MIN_POSITION_QTY,
        "min_position_usd": _MIN_POSITION_USD,
        "last_price": last_price,
    }


def _read_state() -> dict[str, Any]:
    try:
        p = Path(_STATE_PATH)
        if not p.exists():
            return {}
        return json.loads(p.read_text(encoding="utf-8") or "{}")
    except Exception as e:
        logger.debug("system_core: read equity state failed: %s", e)
        return {}


def _write_state(data: dict[str, Any]) -> None:
    try:
        p = Path(_STATE_PATH)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=0), encoding="utf-8")
    except Exception as e:
        logger.warning("system_core: write equity state failed: %s", e)


def _net_equity_usd(db: Session) -> float:
    """Net wallet equity: latest balance per currency minus active borrowed USD."""
    from app.models.portfolio import PortfolioBalance

    assets = 0.0
    try:
        table = PortfolioBalance.__tablename__
        result = db.execute(
            text(
                f"""
                SELECT COALESCE(SUM(usd_value), 0)
                FROM (
                    SELECT usd_value,
                           ROW_NUMBER() OVER (PARTITION BY currency ORDER BY id DESC) AS rn
                    FROM {table}
                ) ranked
                WHERE rn = 1 AND usd_value > 0
                """
            )
        ).scalar()
        assets = float(result or 0)
    except Exception as e:
        logger.debug("system_core: deduped asset sum failed: %s", e)
        return 0.0

    borrowed = 0.0
    try:
        from app.models.portfolio_loan import PortfolioLoan

        borrowed_result = (
            db.query(func.sum(PortfolioLoan.borrowed_usd_value))
            .filter(PortfolioLoan.is_active == True)  # noqa: E712
            .scalar()
        )
        borrowed = float(borrowed_result or 0)
    except Exception as e:
        logger.debug("system_core: borrowed sum failed: %s", e)

    if assets <= 0:
        return 0.0
    return max(assets - borrowed, 0.0)


def _maybe_rebaseline_stale_peak(state: dict[str, Any], eq: float) -> dict[str, Any]:
    """Drop an inflated intraday peak when equity method changed or data was corrected."""
    peak = float(state.get("peak_usd") or 0)
    if peak <= 0 or eq <= 0:
        return state
    if peak >= eq * _STALE_PEAK_RATIO:
        logger.warning(
            "system_core: rebaseline stale peak_usd from %.2f to %.2f (ratio=%.2f threshold=%.2f)",
            peak,
            eq,
            peak / eq,
            _STALE_PEAK_RATIO,
        )
        state["peak_usd"] = eq
    return state


def refresh_daily_equity_peak(db: Session) -> None:
    """Track intraday peak net equity (UTC date) for drawdown guard."""
    if not _GUARDS_ON:
        logger.debug("system_core: equity_peak_refresh skipped guards_disabled")
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eq = _net_equity_usd(db)
    if eq <= 0:
        logger.info(
            "system_core: equity_peak_refresh skipped reason=no_net_equity_usd date=%s",
            today,
        )
        return
    state = _read_state()
    if state.get("date") != today:
        state = {"date": today, "peak_usd": eq}
    else:
        state = _maybe_rebaseline_stale_peak(state, eq)
        prev = float(state.get("peak_usd") or eq)
        state["peak_usd"] = max(prev, eq)
    _write_state(state)
    logger.info(
        "system_core: equity_peak_refresh ok date=%s peak_usd=%.4f current_eq_usd=%.4f state_path=%s",
        state.get("date"),
        float(state.get("peak_usd") or 0),
        eq,
        _STATE_PATH,
    )


def _daily_drawdown_violation(db: Session) -> Tuple[bool, str]:
    if not _GUARDS_ON:
        return False, ""
    eq = _net_equity_usd(db)
    if eq <= 0:
        return False, ""
    state = _read_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("date") != today:
        return False, ""
    original_peak = float(state.get("peak_usd") or 0)
    state = _maybe_rebaseline_stale_peak(state, eq)
    new_peak = float(state.get("peak_usd") or 0)
    if new_peak != original_peak:
        _write_state({**state, "date": today})
    peak = new_peak
    if peak <= 0:
        return False, ""
    dd_pct = 100.0 * (peak - eq) / peak
    if dd_pct > _MAX_DRAWDOWN_PCT + 1e-9:
        return True, f"system_core_daily_drawdown dd_pct={dd_pct:.2f} peak={peak:.2f} now={eq:.2f}"
    return False, ""


def count_distinct_symbols_with_open_positions(db: Session) -> int:
    from app.models.watchlist import WatchlistItem
    from app.services.order_position_service import count_open_positions_for_symbol

    seen: set[str] = set()
    n = 0
    try:
        for (sym,) in db.query(WatchlistItem.symbol).filter(WatchlistItem.is_deleted == False).distinct():  # noqa: E712
            if not sym:
                continue
            base = sym.split("_")[0].upper() if "_" in sym else sym.upper()
            if base in seen:
                continue
            seen.add(base)
            try:
                if count_open_positions_for_symbol(db, base, **_position_dust_kwargs()) > 0:
                    n += 1
            except Exception:
                continue
    except Exception as e:
        logger.debug("system_core: count open symbols failed: %s", e)
    return n


def check_system_core_buy_allowed(
    db: Session,
    symbol: str,
    amount_usd: float,
    *,
    rsi: float | None,
    ma200: float | None,
    price: float,
) -> Tuple[bool, str]:
    """
    Returns (allowed, reason). When guards disabled, always (True, "").
    """
    if not _GUARDS_ON:
        return True, ""

    sym = (symbol or "").strip().upper()
    base = sym.split("_")[0] if "_" in sym else sym

    if amount_usd > _MAX_PER_TRADE + 1e-6:
        return False, f"system_core_max_trade_usd amount={amount_usd} max={_MAX_PER_TRADE}"

    dd_block, dd_reason = _daily_drawdown_violation(db)
    if dd_block:
        return False, dd_reason

    try:
        from app.services.order_position_service import count_open_positions_for_symbol

        max_per_coin = _resolve_max_open_per_coin()
        open_for_symbol = count_open_positions_for_symbol(db, base, **_position_dust_kwargs(price))
        if open_for_symbol >= max_per_coin:
            return False, "system_core_one_active_trade_per_coin"

        max_open_trades = _resolve_max_open_trades()
        open_symbols = count_distinct_symbols_with_open_positions(db)
        if open_symbols >= max_open_trades:
            return False, f"system_core_max_open_trades count={open_symbols} max={max_open_trades}"
    except Exception as e:
        logger.warning("system_core: position checks failed (allowing): %s", e)

    if rsi is not None and rsi >= _RSI_BUY_MAX:
        return False, f"system_core_rsi rsi={rsi} need_lt_{_RSI_BUY_MAX:g}"

    if ma200 is not None and ma200 > 0 and price > 0 and price <= ma200:
        return False, f"system_core_ma200 price={price} ma200={ma200}"

    return True, ""


def check_system_core_short_entry_allowed(
    db: Session,
    symbol: str,
    amount_usd: float,
    *,
    price: float,
) -> Tuple[bool, str]:
    """Position/exposure gates for a SHORT ENTRY (a margin SELL that opens a NEW position).

    A short entry increases open exposure, so it must obey the same amount cap, daily-drawdown,
    one-active-per-coin and max-open-trades limits as a BUY. The RSI/MA200 gates are BUY-specific
    and are NOT applied here. Closing SELLs (which reduce exposure) must NOT be routed through
    this guard.

    Returns (allowed, reason). When guards are disabled, always (True, "").
    """
    if not _GUARDS_ON:
        return True, ""

    sym = (symbol or "").strip().upper()
    base = sym.split("_")[0] if "_" in sym else sym

    if amount_usd > _MAX_PER_TRADE + 1e-6:
        return False, f"system_core_max_trade_usd amount={amount_usd} max={_MAX_PER_TRADE}"

    dd_block, dd_reason = _daily_drawdown_violation(db)
    if dd_block:
        return False, dd_reason

    try:
        from app.services.order_position_service import count_open_positions_for_symbol

        max_per_coin = _resolve_max_open_per_coin()
        open_for_symbol = count_open_positions_for_symbol(db, base, **_position_dust_kwargs(price))
        if open_for_symbol >= max_per_coin:
            return False, "system_core_one_active_trade_per_coin"

        max_open_trades = _resolve_max_open_trades()
        open_symbols = count_distinct_symbols_with_open_positions(db)
        if open_symbols >= max_open_trades:
            return False, f"system_core_max_open_trades count={open_symbols} max={max_open_trades}"
    except Exception as e:
        logger.warning("system_core: short-entry position checks failed (allowing): %s", e)

    return True, ""


# Backward-compatible alias for tests/callers that referenced the old gross-sum helper.
def _sum_portfolio_usd(db: Session) -> float:
    return _net_equity_usd(db)
