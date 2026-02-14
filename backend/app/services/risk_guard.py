"""
Execution-level capital protection. All guardrails actively block unsafe trades.
No soft warnings; violations raise RiskViolationError and emit monitoring event.
"""
import logging
from typing import Optional

from app.services.risk_config import (
    MAX_LEVERAGE,
    MAX_EQUITY_PER_TRADE_PCT,
    MAX_TOTAL_MARGIN_EXPOSURE_PCT,
    MIN_LIQUIDATION_BUFFER_PCT,
    MAX_DAILY_LOSS_PCT,
    GLOBAL_TRADING_ENABLED,
)
from app.services.events import InvariantViolation

logger = logging.getLogger(__name__)

# Track when daily loss stop has triggered (for health reporting)
_daily_loss_triggered: bool = False


def _emit_invariant_violation(symbol: Optional[str], reason_code: str, message: str) -> None:
    try:
        from app.services.event_bus import get_event_bus
        get_event_bus().publish(InvariantViolation(
            decision_type="FAILED",
            reason_code=reason_code,
            message=message,
            symbol=symbol,
            source="risk_guard",
        ))
    except Exception as e:
        logger.warning("Failed to emit InvariantViolation: %s", e)


def _block(symbol: Optional[str], reason_code: str, message: str) -> None:
    logger.critical("[RISK_GUARD] BLOCKED: %s - %s", reason_code, message)
    _emit_invariant_violation(symbol, reason_code, message)
    raise RiskViolationError(message, reason_code=reason_code)


class RiskViolationError(Exception):
    """Raised when a risk guard blocks a trade. Do not send order to exchange."""
    def __init__(self, message: str, reason_code: str = "RISK_GUARD_BLOCKED"):
        self.reason_code = reason_code
        super().__init__(message)


def is_daily_loss_triggered() -> bool:
    """Return True if daily loss stop has been triggered (for health)."""
    return _daily_loss_triggered


def get_risk_guard_health() -> dict:
    """Return risk_guard section for system health."""
    return {
        "max_leverage": MAX_LEVERAGE,
        "daily_loss_triggered": _daily_loss_triggered,
        "global_trading_enabled": GLOBAL_TRADING_ENABLED,
    }


def check_trade_allowed(
    *,
    symbol: str,
    side: str,
    is_margin: bool,
    leverage: Optional[float],
    trade_value_usd: float,
    entry_price: Optional[float],
    account_equity: float,
    total_margin_exposure: float,
    daily_loss_pct: float,
    trade_on_margin_from_watchlist: bool,
) -> None:
    """
    Validate trade against all risk guardrails. Raise RiskViolationError if any check fails.
    If trade_on_margin_from_watchlist is False, margin is forced off (spot only).
    """
    global _daily_loss_triggered

    # Margin option consistency: watchlist says no margin -> force spot
    if not trade_on_margin_from_watchlist:
        is_margin = False

    # A) Global kill switch
    if not GLOBAL_TRADING_ENABLED:
        _block(symbol, "RISK_GUARD_BLOCKED", "Global trading is disabled (GLOBAL_TRADING_ENABLED=false)")

    # B) Leverage cap (margin only)
    if is_margin:
        if leverage is None:
            _block(symbol, "RISK_GUARD_BLOCKED", "Margin trade requires leverage to be set")
        if float(leverage) > MAX_LEVERAGE:
            _block(
                symbol,
                "RISK_GUARD_BLOCKED",
                f"Leverage {leverage} exceeds cap {MAX_LEVERAGE}",
            )
    # else: spot, no leverage check

    # C) Equity per trade cap
    if account_equity <= 0:
        _block(symbol, "RISK_GUARD_BLOCKED", "Account equity must be positive to trade")
    pct = (trade_value_usd / account_equity) * 100.0
    if pct > MAX_EQUITY_PER_TRADE_PCT:
        _block(
            symbol,
            "RISK_GUARD_BLOCKED",
            f"Trade size {pct:.2f}% of equity exceeds max {MAX_EQUITY_PER_TRADE_PCT}%",
        )

    # D) Total margin exposure cap
    if account_equity > 0:
        exposure_pct = (total_margin_exposure / account_equity) * 100.0
        if exposure_pct > MAX_TOTAL_MARGIN_EXPOSURE_PCT:
            _block(
                symbol,
                "RISK_GUARD_BLOCKED",
                f"Total margin exposure {exposure_pct:.2f}% exceeds cap {MAX_TOTAL_MARGIN_EXPOSURE_PCT}%",
            )

    # E) Liquidation buffer (margin only, approximation: distance = 1/leverage * 100)
    if is_margin and leverage is not None and entry_price is not None and entry_price > 0:
        lev = float(leverage)
        if lev <= 0:
            _block(symbol, "RISK_GUARD_BLOCKED", "Leverage must be positive")
        distance_pct = (1.0 / lev) * 100.0
        if distance_pct < MIN_LIQUIDATION_BUFFER_PCT:
            _block(
                symbol,
                "RISK_GUARD_BLOCKED",
                f"Liquidation buffer {distance_pct:.2f}% below minimum {MIN_LIQUIDATION_BUFFER_PCT}%",
            )

    # F) Daily loss stop
    if daily_loss_pct >= MAX_DAILY_LOSS_PCT:
        _daily_loss_triggered = True
        _block(
            symbol,
            "RISK_GUARD_BLOCKED",
            f"Daily loss {daily_loss_pct:.2f}% >= max {MAX_DAILY_LOSS_PCT}% - all trades blocked for remainder of day",
        )
