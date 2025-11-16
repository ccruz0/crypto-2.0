"""
Margin Decision Helper

Centralized logic to decide trading mode (MARGIN vs SPOT) and leverage for a given symbol.
This ensures we never request leverage higher than the maximum allowed, preventing error 306.

Uses dynamic leverage cache that learns from actual order failures and adjusts per pair.
"""
import logging
from typing import Optional
from dataclasses import dataclass

from app.services.margin_info_service import get_margin_info_for_symbol
from app.services.margin_leverage_cache import get_leverage_cache

logger = logging.getLogger(__name__)

# Default configured leverage (can be made configurable later)
DEFAULT_CONFIGURED_LEVERAGE = 10.0


@dataclass
class TradingModeDecision:
    """Decision about trading mode and leverage for an order"""
    use_margin: bool
    leverage: Optional[float]  # None if SPOT, otherwise the leverage to use
    reason: str  # Human-readable reason for logging


def decide_trading_mode(
    symbol: str,
    configured_leverage: Optional[float] = None,
    user_wants_margin: bool = True
) -> TradingModeDecision:
    """
    Decide trading mode (MARGIN vs SPOT) and leverage for a given symbol.
    
    Args:
        symbol: Trading symbol (e.g., "ADA_USDT", "DOGE_USDT")
        configured_leverage: User's configured leverage (defaults to DEFAULT_CONFIGURED_LEVERAGE)
        user_wants_margin: Whether user has enabled margin trading in settings
    
    Returns:
        TradingModeDecision with:
        - use_margin: bool (True for margin, False for SPOT)
        - leverage: Optional[float] (None for SPOT, otherwise the leverage to use)
        - reason: str (for logging)
    
    Logic:
        1. If user doesn't want margin, return SPOT
        2. Fetch margin info for symbol
        3. If margin not enabled for symbol, return SPOT
        4. Calculate final leverage = min(configured, max_allowed)
        5. If final leverage < 1, return SPOT (safety check)
        6. Otherwise return MARGIN with calculated leverage
    """
    if configured_leverage is None:
        configured_leverage = DEFAULT_CONFIGURED_LEVERAGE
    
    # Step 1: If user doesn't want margin, use SPOT
    if not user_wants_margin:
        return TradingModeDecision(
            use_margin=False,
            leverage=None,
            reason=f"User has margin trading disabled"
        )
    
    # Step 2: Fetch margin info for symbol
    try:
        margin_info = get_margin_info_for_symbol(symbol)
    except Exception as e:
        logger.error(f"Error fetching margin info for {symbol}: {e}", exc_info=True)
        # On error, default to SPOT for safety
        return TradingModeDecision(
            use_margin=False,
            leverage=None,
            reason=f"Error fetching margin info, defaulting to SPOT: {str(e)}"
        )
    
    # Step 3: If margin not enabled for this symbol, use SPOT
    if not margin_info.margin_trading_enabled:
        return TradingModeDecision(
            use_margin=False,
            leverage=None,
            reason=f"Margin trading not enabled for {symbol} (per Crypto.com Exchange)"
        )
    
    # Step 4: Calculate final leverage using dynamic cache
    # The cache learns from actual order failures and adjusts per pair
    leverage_cache = get_leverage_cache()
    
    # Get cached max working leverage (learned from previous orders)
    max_allowed = margin_info.max_leverage
    
    # Check if we have REAL verified cache (not just initial conservative value)
    cached_info = leverage_cache._cache.get(symbol.upper())
    has_verified_cache = cached_info and cached_info.max_working_leverage is not None and cached_info.verification_attempts > 0
    
    cached_max_working = leverage_cache.get_max_working_leverage(
        symbol=symbol,
        api_max_leverage=max_allowed,
        configured_leverage=configured_leverage
    )
    
    # Strategy: Start LOW and work UP (2x → 3x → 5x → 10x)
    # This is more efficient than starting high and working down
    # If 2x works, next order will try 3x, then 5x, then 10x
    # If any fails, we reduce back down
    
    # Only try to increase leverage if we have VERIFIED cache (from successful order)
    # If cached_max_working is just initial conservative value (2x), use it as-is
    if cached_max_working is not None and has_verified_cache:
        # We have a known working leverage - this is our MINIMUM working leverage
        # Try to increase it: if cached is 2x, try 3x; if 3x, try 5x; etc.
        leverage_steps = [2.0, 3.0, 5.0, 10.0]
        next_step = None
        for step in leverage_steps:
            if step > cached_max_working and step <= configured_leverage:
                if max_allowed is None or step <= max_allowed:
                    next_step = step
                    break
        
        if next_step:
            final_leverage = next_step
            logger.info(
                f"Trying higher leverage for {symbol}: {cached_max_working}x → {final_leverage}x "
                f"(known working: {cached_max_working}x)"
            )
        else:
            # Already at max, use cached
            final_leverage = cached_max_working
            logger.info(
                f"Using cached working leverage {final_leverage}x for {symbol} "
                f"(already at maximum)"
            )
    elif cached_max_working is not None:
        # We have cache but it's NOT verified yet (initial conservative value, usually 2x)
        # Use it as-is, don't try to increase
        final_leverage = cached_max_working
        logger.info(
            f"Using initial conservative leverage {final_leverage}x for {symbol} "
            f"(not yet verified - will verify with this order, then try higher)"
        )
    elif max_allowed is not None:
        # No cache at all - start with 2x (conservative)
        if max_allowed >= 2.0 and configured_leverage >= 2.0:
            final_leverage = 2.0
            logger.info(
                f"Starting with conservative leverage 2x for {symbol} "
                f"(will increase to 3x, 5x, 10x if successful, max allowed: {max_allowed}x)"
            )
        else:
            final_leverage = min(configured_leverage, max_allowed)
    else:
        # Margin enabled but no max_leverage info - start with 2x
        if configured_leverage >= 2.0:
            final_leverage = 2.0
            logger.info(
                f"Starting with conservative leverage 2x for {symbol} "
                f"(will increase to 3x, 5x, 10x if successful)"
            )
        else:
            final_leverage = configured_leverage
    
    # Step 5: Safety check - if leverage < 1, use SPOT
    if final_leverage < 1:
        return TradingModeDecision(
            use_margin=False,
            leverage=None,
            reason=f"Calculated leverage {final_leverage}x < 1, defaulting to SPOT for safety"
        )
    
    # Step 6: Return MARGIN with calculated leverage
    if final_leverage < configured_leverage:
        reason = (
            f"Using {final_leverage}x leverage (configured: {configured_leverage}x, "
            f"max allowed for {symbol}: {max_allowed}x)"
        )
    else:
        reason = (
            f"Using {final_leverage}x leverage (configured: {configured_leverage}x, "
            f"max allowed for {symbol}: {max_allowed}x)"
        )
    
    return TradingModeDecision(
        use_margin=True,
        leverage=final_leverage,
        reason=reason
    )


def log_margin_decision(
    symbol: str,
    decision: TradingModeDecision,
    configured_leverage: Optional[float] = None
):
    """
    Log margin decision in a standardized format for debugging.
    
    This creates log entries like:
    [MARGIN_DECISION] symbol=ADA_USDT configured_lev=10 max_allowed=5 final_lev=5 use_margin=True
    """
    if configured_leverage is None:
        configured_leverage = DEFAULT_CONFIGURED_LEVERAGE
    
    # Get margin info to log max_allowed
    try:
        margin_info = get_margin_info_for_symbol(symbol)
        max_allowed = margin_info.max_leverage if margin_info.margin_trading_enabled else None
    except:
        max_allowed = None
    
    logger.info(
        f"[MARGIN_DECISION] symbol={symbol} "
        f"configured_lev={configured_leverage} "
        f"max_allowed={max_allowed} "
        f"final_lev={decision.leverage} "
        f"use_margin={decision.use_margin} "
        f"reason={decision.reason}"
    )

