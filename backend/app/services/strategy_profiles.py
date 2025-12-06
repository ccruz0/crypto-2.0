"""Helpers to resolve strategy type and risk approach per symbol."""
from __future__ import annotations

import logging
from enum import Enum
from pathlib import Path
from typing import Any, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.config_loader import load_config

try:
    from app.models.trade_signal import TradeSignal
except ImportError:  # pragma: no cover
    TradeSignal = None  # type: ignore

logger = logging.getLogger(__name__)


class StrategyType(str, Enum):
    """Trading strategy archetypes."""

    SWING = "swing"
    INTRADAY = "intraday"
    SCALP = "scalp"


class RiskApproach(str, Enum):
    """Risk appetite for signal execution."""

    CONSERVATIVE = "conservative"
    AGGRESSIVE = "aggressive"


_CONFIG_CACHE: Optional[dict[str, Any]] = None
_CONFIG_MTIME: Optional[float] = None
_CONFIG_PATH = Path("trading_config.json")


def _load_config_cached() -> dict[str, Any]:
    global _CONFIG_CACHE, _CONFIG_MTIME
    try:
        mtime = _CONFIG_PATH.stat().st_mtime
    except FileNotFoundError:
        mtime = None
    if _CONFIG_CACHE is None or _CONFIG_MTIME != mtime:
        _CONFIG_CACHE = load_config()
        _CONFIG_MTIME = mtime
    return _CONFIG_CACHE or {}


def _normalize_strategy(value: Optional[Any]) -> Optional[StrategyType]:
    if value is None:
        return None
    raw = str(getattr(value, "value", value)).lower()
    if "-" in raw:
        raw = raw.split("-", 1)[0]
    try:
        return StrategyType(raw)
    except ValueError:
        logger.debug("Unknown strategy type '%s' - defaulting later", raw)
        return None


def _normalize_approach(value: Optional[Any]) -> Optional[RiskApproach]:
    if value is None:
        return None
    raw = str(getattr(value, "value", value)).lower()
    if "-" in raw:
        raw = raw.split("-", 1)[-1]
    try:
        return RiskApproach(raw)
    except ValueError:
        logger.debug("Unknown risk approach '%s' - defaulting later", raw)
        return None


def _parse_preset(preset_name: Optional[str]) -> Tuple[Optional[StrategyType], Optional[RiskApproach]]:
    if not preset_name:
        return None, None
    normalized = str(preset_name).lower()
    parts = normalized.split("-", 1)
    strategy = _normalize_strategy(parts[0])
    approach = _normalize_approach(parts[1]) if len(parts) > 1 else None
    return strategy, approach


def resolve_strategy_profile(
    symbol: str,
    db: Optional[Session] = None,
    watchlist_item: Optional[Any] = None,
) -> Tuple[StrategyType, RiskApproach]:
    """
    Determine the (strategy_type, risk_approach) tuple for the given symbol.

    Priority:
        1. Watchlist overrides for risk approach (sl_tp_mode)
        2. TradeSignal row (preset + sl_profile) if available via DB
        3. trading_config.json preset for the symbol (or defaults)
        4. Fallback to (SWING, CONSERVATIVE)
    """

    strategy: Optional[StrategyType] = None
    approach: Optional[RiskApproach] = None

    # 1) Watchlist overrides - only affect approach
    if watchlist_item is not None:
        approach = _normalize_approach(getattr(watchlist_item, "sl_tp_mode", None))

    symbol_key = (symbol or "").upper()

    # 2) Use trading_config preset mapping (dashboard is the source of truth)
    cfg = _load_config_cached()
    coins_cfg = cfg.get("coins", {})
    coin_cfg = coins_cfg.get(symbol_key) or coins_cfg.get(symbol_key.replace("_USDT", "_USD")) or {}
    preset_name = coin_cfg.get("preset") or cfg.get("defaults", {}).get("preset")
    preset_strategy, preset_approach = _parse_preset(preset_name)

    if strategy is None:
        strategy = preset_strategy
    if approach is None:
        approach = preset_approach

    # 3) Fall back to database trade_signals if still unresolved
    if strategy is None or approach is None:
        try:
            if db is not None and TradeSignal is not None:
                trade_signal = (
                    db.query(TradeSignal)
                    .filter(TradeSignal.symbol == symbol_key)
                    .first()
                )
                if trade_signal:
                    if strategy is None:
                        strategy = _normalize_strategy(getattr(trade_signal, "preset", None))
                    if approach is None:
                        approach = _normalize_approach(getattr(trade_signal, "sl_profile", None))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Could not read trade signal for %s: %s", symbol_key, exc)

    # 4) Final fallbacks
    if strategy is None:
        strategy = StrategyType.SWING
    if approach is None:
        approach = RiskApproach.CONSERVATIVE

    return strategy, approach

