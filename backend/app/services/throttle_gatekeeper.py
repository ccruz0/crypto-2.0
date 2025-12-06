"""Universal throttle gatekeeper.

This module provides a final, non-bypassable gate that enforces throttle rules
for ALL alert and order emissions. No alert or order can be emitted without
passing through this gate.
"""
import logging
from typing import Dict, Any, Optional, Tuple
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def enforce_throttle(
    *,
    symbol: str,
    side: str,
    current_price: float,
    throttle_allowed: bool,
    throttle_reason: str,
    throttle_metadata: Optional[Dict[str, Any]] = None,
) -> Tuple[bool, str]:
    """
    Universal throttle gatekeeper - final check before ANY alert or order emission.
    
    This function MUST be called before:
    - Sending Telegram alerts
    - Creating orders
    - Any other alert emission
    
    Args:
        symbol: Trading symbol (e.g., "BTC_USDT")
        side: Signal side ("BUY" or "SELL")
        current_price: Current price
        throttle_allowed: Result from should_emit_signal() throttle check
        throttle_reason: Reason from throttle check
        throttle_metadata: Optional metadata from throttle check
        
    Returns:
        Tuple of (allowed: bool, final_reason: str)
        - allowed: True only if throttle check passed
        - final_reason: Explanation of decision
    """
    side = side.upper()
    symbol_upper = symbol.upper()
    
    # Extract metadata if available
    time_since_last = None
    price_change_pct = None
    blocked_by_time = False
    blocked_by_price = False
    
    if throttle_metadata:
        time_since_last = throttle_metadata.get("time_since_last")
        price_change_pct = throttle_metadata.get("price_change_pct")
        blocked_by_time = throttle_metadata.get("blocked_by_time", False)
        blocked_by_price = throttle_metadata.get("blocked_by_price", False)
    
    # BTC-specific logging (always log for BTC)
    is_btc = symbol_upper in ("BTC_USDT", "BTC_USD", "BTC")
    
    if throttle_allowed:
        # Throttle check passed - allow emission
        reason_text = f"Throttle check PASSED: {throttle_reason}"
        
        if is_btc:
            logger.info(
                "[THROTTLE_ALLOWED] [BTC] symbol=%s side=%s price=%.4f "
                "time_since_last=%.2f price_change_pct=%.2f reason=%s",
                symbol,
                side,
                current_price,
                time_since_last or 0.0,
                price_change_pct or 0.0,
                throttle_reason,
            )
        else:
            logger.debug(
                "[THROTTLE_ALLOWED] symbol=%s side=%s price=%.4f reason=%s",
                symbol,
                side,
                current_price,
                throttle_reason,
            )
        
        return True, reason_text
    else:
        # Throttle check failed - BLOCK emission
        reason_text = f"Throttle check FAILED: {throttle_reason}"
        
        # Always log blocked attempts, especially for BTC
        logger.warning(
            "[THROTTLE_BLOCKED] symbol=%s side=%s price=%.4f "
            "time_since_last=%.2f price_change_pct=%.2f "
            "blocked_by_time=%s blocked_by_price=%s reason=%s",
            symbol,
            side,
            current_price,
            time_since_last or 0.0,
            price_change_pct or 0.0,
            blocked_by_time,
            blocked_by_price,
            throttle_reason,
        )
        
        if is_btc:
            logger.error(
                "[THROTTLE_BLOCKED] [BTC] ⚠️ BTC alert BLOCKED by throttle: "
                "symbol=%s side=%s price=%.4f reason=%s",
                symbol,
                side,
                current_price,
                throttle_reason,
            )
        
        return False, reason_text


def log_throttle_decision(
    *,
    symbol: str,
    side: str,
    current_price: float,
    throttle_allowed: bool,
    throttle_reason: str,
    throttle_metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log throttle decision with structured tags.
    
    This is a logging-only function (doesn't block) for audit purposes.
    """
    side = side.upper()
    symbol_upper = symbol.upper()
    is_btc = symbol_upper in ("BTC_USDT", "BTC_USD", "BTC")
    
    time_since_last = throttle_metadata.get("time_since_last") if throttle_metadata else None
    price_change_pct = throttle_metadata.get("price_change_pct") if throttle_metadata else None
    blocked_by_time = throttle_metadata.get("blocked_by_time", False) if throttle_metadata else False
    blocked_by_price = throttle_metadata.get("blocked_by_price", False) if throttle_metadata else False
    
    logger.info(
        "[THROTTLE_DECISION] symbol=%s side=%s allowed=%s price=%.4f "
        "time_since_last=%.2f price_change_pct=%.2f "
        "blocked_by_time=%s blocked_by_price=%s reason=%s",
        symbol,
        side,
        throttle_allowed,
        current_price,
        time_since_last or 0.0,
        price_change_pct or 0.0,
        blocked_by_time,
        blocked_by_price,
        throttle_reason,
    )
    
    if is_btc:
        logger.info(
            "[THROTTLE_DECISION] [BTC] BTC throttle decision: "
            "symbol=%s side=%s allowed=%s reason=%s",
            symbol,
            side,
            throttle_allowed,
            throttle_reason,
        )










