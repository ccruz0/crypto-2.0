"""
Global risk configuration for capital protection.
Hard defaults; override via environment. Invalid values raise at startup.
"""
import os
import logging

logger = logging.getLogger(__name__)

# Hard defaults
_MAX_LEVERAGE_DEFAULT = 5
_MAX_EQUITY_PER_TRADE_PCT_DEFAULT = 10
_MAX_TOTAL_MARGIN_EXPOSURE_PCT_DEFAULT = 40
_MIN_LIQUIDATION_BUFFER_PCT_DEFAULT = 15
_MAX_DAILY_LOSS_PCT_DEFAULT = 5
_GLOBAL_TRADING_ENABLED_DEFAULT = True


def _float_env(name: str, default: float, min_val: float, max_val: float) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = float(raw.strip())
    except ValueError:
        raise ValueError(f"{name} must be a number, got: {raw!r}")
    if not (min_val <= v <= max_val):
        raise ValueError(f"{name} must be in [{min_val}, {max_val}], got: {v}")
    return v


def _bool_env(name: str, default: bool) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if raw in ("", "1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    if raw:
        raise ValueError(f"{name} must be true/false or 1/0, got: {raw!r}")
    return default


def _load_all() -> None:
    """Load and validate all risk config. Raise on invalid. Sets module globals."""
    global MAX_LEVERAGE, MAX_EQUITY_PER_TRADE_PCT, MAX_TOTAL_MARGIN_EXPOSURE_PCT
    global MIN_LIQUIDATION_BUFFER_PCT, MAX_DAILY_LOSS_PCT, GLOBAL_TRADING_ENABLED
    MAX_LEVERAGE = _float_env("RISK_MAX_LEVERAGE", _MAX_LEVERAGE_DEFAULT, 1.0, 100.0)
    MAX_EQUITY_PER_TRADE_PCT = _float_env("RISK_MAX_EQUITY_PER_TRADE_PCT", _MAX_EQUITY_PER_TRADE_PCT_DEFAULT, 0.1, 100.0)
    MAX_TOTAL_MARGIN_EXPOSURE_PCT = _float_env("RISK_MAX_TOTAL_MARGIN_EXPOSURE_PCT", _MAX_TOTAL_MARGIN_EXPOSURE_PCT_DEFAULT, 0.0, 100.0)
    MIN_LIQUIDATION_BUFFER_PCT = _float_env("RISK_MIN_LIQUIDATION_BUFFER_PCT", _MIN_LIQUIDATION_BUFFER_PCT_DEFAULT, 1.0, 100.0)
    MAX_DAILY_LOSS_PCT = _float_env("RISK_MAX_DAILY_LOSS_PCT", _MAX_DAILY_LOSS_PCT_DEFAULT, 0.0, 100.0)
    GLOBAL_TRADING_ENABLED = _bool_env("RISK_GLOBAL_TRADING_ENABLED", _GLOBAL_TRADING_ENABLED_DEFAULT)


_load_all()

__all__ = [
    "MAX_LEVERAGE",
    "MAX_EQUITY_PER_TRADE_PCT",
    "MAX_TOTAL_MARGIN_EXPOSURE_PCT",
    "MIN_LIQUIDATION_BUFFER_PCT",
    "MAX_DAILY_LOSS_PCT",
    "GLOBAL_TRADING_ENABLED",
]
