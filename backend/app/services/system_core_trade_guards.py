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

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_MAX_PER_TRADE = float(os.getenv("SYSTEM_CORE_MAX_TRADE_USD", "1000"))
_MAX_OPEN_TRADES = int(os.getenv("SYSTEM_CORE_MAX_OPEN_TRADES", "5"))
_MAX_DRAWDOWN_PCT = float(os.getenv("SYSTEM_CORE_MAX_DAILY_DRAWDOWN_PCT", "5"))
_STATE_PATH = os.getenv("SYSTEM_CORE_EQUITY_STATE_PATH", "/tmp/system_core_equity_state.json")
_GUARDS_ON = (os.getenv("SYSTEM_CORE_GUARDS_ENABLED", "true").strip().lower() not in ("0", "false", "no", "off"))


def system_core_guards_enabled() -> bool:
    return _GUARDS_ON


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


def _sum_portfolio_usd(db: Session) -> float:
    try:
        from app.models.portfolio import PortfolioBalance

        rows = db.query(PortfolioBalance.usd_value).all()
        total = 0.0
        for (v,) in rows:
            if v is not None:
                try:
                    total += float(v)
                except (TypeError, ValueError):
                    continue
        return total
    except Exception as e:
        logger.debug("system_core: portfolio sum failed: %s", e)
        return 0.0


def refresh_daily_equity_peak(db: Session) -> None:
    """Track intraday peak equity (UTC date) for drawdown guard."""
    if not _GUARDS_ON:
        logger.debug("system_core: equity_peak_refresh skipped guards_disabled")
        return
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    eq = _sum_portfolio_usd(db)
    if eq <= 0:
        logger.info(
            "system_core: equity_peak_refresh skipped reason=no_portfolio_usd (sum PortfolioBalance.usd_value<=0) date=%s",
            today,
        )
        return
    state = _read_state()
    if state.get("date") != today:
        state = {"date": today, "peak_usd": eq}
    else:
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
    eq = _sum_portfolio_usd(db)
    if eq <= 0:
        return False, ""
    state = _read_state()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    if state.get("date") != today:
        return False, ""
    peak = float(state.get("peak_usd") or 0)
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
        for (sym,) in db.query(WatchlistItem.symbol).filter(WatchlistItem.is_deleted == False).distinct():
            if not sym:
                continue
            base = sym.split("_")[0].upper() if "_" in sym else sym.upper()
            if base in seen:
                continue
            seen.add(base)
            try:
                if count_open_positions_for_symbol(db, base) > 0:
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

        if count_open_positions_for_symbol(db, base) > 0:
            return False, "system_core_one_active_trade_per_coin"

        open_symbols = count_distinct_symbols_with_open_positions(db)
        if open_symbols >= _MAX_OPEN_TRADES:
            return False, f"system_core_max_open_trades count={open_symbols} max={_MAX_OPEN_TRADES}"
    except Exception as e:
        logger.warning("system_core: position checks failed (allowing): %s", e)

    if rsi is not None and rsi >= 40:
        return False, f"system_core_rsi rsi={rsi} need_lt_40"

    if ma200 is not None and ma200 > 0 and price > 0 and price <= ma200:
        return False, f"system_core_ma200 price={price} ma200={ma200}"

    return True, ""
