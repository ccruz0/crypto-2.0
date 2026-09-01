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
# Short entry: block when RSI is overbought AND the alert trigger is a rising price
# (APT 2026-09-01: ↑1.27% + RSI>70 opened a short into momentum).
_RSI_SELL_OVERBOUGHT = float(os.getenv("SYSTEM_CORE_RSI_SELL_OVERBOUGHT", "70"))
# Dust: net filled remnant below these thresholds does not count as an open position for one-per-coin.
_MIN_POSITION_QTY = float(os.getenv("SYSTEM_CORE_MIN_POSITION_QTY", "0"))
_MIN_POSITION_USD = float(os.getenv("SYSTEM_CORE_MIN_POSITION_USD", "5"))
# Regime filter para cortos (2026-08-22, decision de Carlos): un corto solo se
# abre con el precio POR DEBAJO de su MA200 (espejo del gate de compra).
# Kill-switch sin deploy: SHORT_REQUIRE_PRICE_BELOW_MA200=false.
_SHORT_REGIME_ON = (
    os.getenv("SHORT_REQUIRE_PRICE_BELOW_MA200", "true").strip().lower()
    not in ("0", "false", "no", "off")
)
# Regime filter de mercado para largos (2026-08-23, decision de Carlos):
# ninguna COMPRA en alts con BTC por debajo de su MA200 diaria. Medido en
# 4 anos / 13 alts: retorno medio diario de las alts ~0% con BTC>MA200
# frente a ~-22% anualizado con BTC<MA200. Vive en la puerta comun de
# compra para cortar CUALQUIER ruta de entrada (incluida Auto).
# Kill-switch sin deploy: LONG_REQUIRE_BTC_ABOVE_MA200=false.
_LONG_BTC_REGIME_ON = (
    os.getenv("LONG_REQUIRE_BTC_ABOVE_MA200", "true").strip().lower()
    not in ("0", "false", "no", "off")
)


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

    if _LONG_BTC_REGIME_ON:
        blocked, regime_reason = _long_btc_regime_block(db)
        if blocked:
            return False, regime_reason

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


def _short_regime_block(db: Session, sym: str, base: str, price: float) -> Tuple[bool, str]:
    """Regime filter para cortos: exige price < MA200 para abrir un corto.

    Decision de Carlos, 2026-08-22. Motivo medido: 37/38 entradas del
    19-21 ago fueron cortos con price>ma200 en pleno rally, y el mercado
    barrio el libro (11 stops en 24h, -177 USD). Es el espejo del gate de
    compra (que bloquea BUY con price<=ma200).

    FAIL-CLOSED: sin MA200 valida no se abre el corto (a diferencia de los
    checks de posicion, que son fail-open). Un filtro de regimen que falla
    abierto no filtra nada, como demostro el contador de posiciones (#523).
    """
    try:
        row = db.execute(
            text(
                "SELECT ma200 FROM market_data "
                "WHERE symbol IN (:s, :b, :b_usd, :b_usdt) AND ma200 IS NOT NULL "
                "ORDER BY CASE symbol WHEN :s THEN 0 WHEN :b_usd THEN 1 WHEN :b_usdt THEN 2 ELSE 3 END "
                "LIMIT 1"
            ),
            {"s": sym, "b": base, "b_usd": f"{base}_USD", "b_usdt": f"{base}_USDT"},
        ).fetchone()
        ma200 = float(row[0]) if row is not None and row[0] is not None else None
    except Exception as e:
        logger.warning("short_regime: ma200 lookup failed for %s: %s", sym, e)
        ma200 = None

    if ma200 is None or ma200 <= 0:
        return True, f"short_regime_ma200_unavailable symbol={sym}"
    if price is None or price <= 0:
        return True, f"short_regime_price_unavailable symbol={sym}"
    if price >= ma200:
        return True, f"short_regime_price_above_ma200 price={price} ma200={ma200}"
    return False, ""


def _long_btc_regime_block(db: Session) -> Tuple[bool, str]:
    """Regime filter de mercado para COMPRAS: exige BTC > MA200 de BTC.

    Decision de Carlos, 2026-08-23. Motivo medido (4 anos, 13 alts): el
    retorno medio diario de las alts es ~0% con BTC sobre su MA200 diaria
    y ~-22% anualizado con BTC por debajo. No predice giros; recorta el
    regimen toxico para cualquier ruta de compra (incluida Auto).

    FAIL-CLOSED: sin precio o MA200 validos de BTC no se compra, igual que
    _short_regime_block. Kill-switch: LONG_REQUIRE_BTC_ABOVE_MA200=false.
    """
    try:
        row = db.execute(
            text(
                "SELECT price, ma200 FROM market_data "
                "WHERE symbol IN ('BTC_USD', 'BTC_USDT') "
                "AND ma200 IS NOT NULL AND price IS NOT NULL "
                "ORDER BY CASE symbol WHEN 'BTC_USD' THEN 0 ELSE 1 END "
                "LIMIT 1"
            )
        ).fetchone()
        btc_price = float(row[0]) if row is not None and row[0] is not None else None
        btc_ma200 = float(row[1]) if row is not None and row[1] is not None else None
    except Exception as e:
        logger.warning("long_btc_regime: BTC price/ma200 lookup failed: %s", e)
        btc_price = None
        btc_ma200 = None

    if btc_ma200 is None or btc_ma200 <= 0:
        return True, "long_btc_regime_ma200_unavailable"
    if btc_price is None or btc_price <= 0:
        return True, "long_btc_regime_price_unavailable"
    if btc_price <= btc_ma200:
        return True, f"long_btc_regime_btc_below_ma200 btc_price={btc_price} btc_ma200={btc_ma200}"
    return False, ""


def check_system_core_short_entry_allowed(
    db: Session,
    symbol: str,
    amount_usd: float,
    *,
    price: float,
    rsi: float | None = None,
    ma200: float | None = None,
    price_rising: bool | None = None,
    ignore_one_active_per_coin: bool = False,
) -> Tuple[bool, str]:
    """Position/exposure gates for a SHORT ENTRY (a margin SELL that opens a NEW position).

    Mirrors BUY regime gates where applicable:
    - BTC > MA200 market regime (``_long_btc_regime_block``)
    - Symbol price < MA200 (``_short_regime_block``)
    - At most one open short per symbol (bot book + material wallet short)
    - Block RSI > 70 when the trigger is a rising price

    ``ignore_one_active_per_coin`` is deprecated and ignored (#619): an existing long
    no longer skips the one-short-per-symbol check; only open *short* exposure counts.

    Returns (allowed, reason). When guards are disabled, always (True, "").
    """
    _ = ma200  # reserved for callers passing snapshot ma200; regime uses DB lookup
    if not _GUARDS_ON:
        return True, ""

    sym = (symbol or "").strip().upper()
    base = sym.split("_")[0] if "_" in sym else sym

    if _LONG_BTC_REGIME_ON:
        blocked, regime_reason = _long_btc_regime_block(db)
        if blocked:
            return False, regime_reason

    if _SHORT_REGIME_ON:
        blocked, regime_reason = _short_regime_block(db, sym, base, price)
        if blocked:
            return False, regime_reason

    if price_rising is True and rsi is not None and rsi > _RSI_SELL_OVERBOUGHT:
        return False, (
            f"system_core_short_rsi_overbought_rising rsi={rsi} "
            f"need_not_rising_or_rsi_lte_{_RSI_SELL_OVERBOUGHT:g}"
        )

    if amount_usd > _MAX_PER_TRADE + 1e-6:
        return False, f"system_core_max_trade_usd amount={amount_usd} max={_MAX_PER_TRADE}"

    dd_block, dd_reason = _daily_drawdown_violation(db)
    if dd_block:
        return False, dd_reason

    try:
        from app.services.order_position_service import (
            count_open_short_positions_for_symbol,
            wallet_has_material_short,
        )

        dust = _position_dust_kwargs(price)
        max_per_coin = _resolve_max_open_per_coin()
        open_shorts = count_open_short_positions_for_symbol(db, base, **dust)
        if open_shorts >= max_per_coin:
            return False, "system_core_one_open_short_per_symbol"
        if wallet_has_material_short(db, base, **dust):
            return False, "system_core_one_open_short_per_symbol"

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
