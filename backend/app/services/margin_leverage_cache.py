"""
Margin Leverage Cache Service

Dynamically adjusts and caches the maximum working leverage per trading pair.
This learns from actual order failures (error 306) and maintains a per-pair leverage limit.
"""
import logging
import time
import json
import os
from typing import Optional, Dict
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

# Cache file location
CACHE_DIR = Path("/tmp/margin_leverage_cache")
CACHE_FILE = CACHE_DIR / "leverage_cache.json"
CACHE_UPDATE_INTERVAL_HOURS = 24  # Verify leverage at least once per day


@dataclass
class PairLeverageInfo:
    """Cached leverage information for a trading pair"""
    symbol: str
    max_working_leverage: Optional[float]  # Maximum leverage that has worked (None if unknown)
    last_verified: float  # Timestamp of last verification
    last_failure_leverage: Optional[float]  # Last leverage that failed (for learning)
    verification_attempts: int  # Number of times we've verified this pair


class MarginLeverageCache:
    """Service to cache and dynamically adjust maximum working leverage per pair"""
    
    def __init__(self):
        self._cache: Dict[str, PairLeverageInfo] = {}
        self._cache_dir = CACHE_DIR
        self._cache_file = CACHE_FILE
        self._load_cache()
    
    def _load_cache(self):
        """Load leverage cache from disk"""
        try:
            if self._cache_file.exists():
                with open(self._cache_file, 'r') as f:
                    data = json.load(f)
                    self._cache = {
                        symbol: PairLeverageInfo(**info)
                        for symbol, info in data.items()
                    }
                logger.info(f"Loaded leverage cache for {len(self._cache)} pairs")
            else:
                # Create cache directory if it doesn't exist
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                logger.info("No existing leverage cache found, starting fresh")
        except Exception as e:
            logger.error(f"Error loading leverage cache: {e}", exc_info=True)
            self._cache = {}
    
    def _save_cache(self):
        """Save leverage cache to disk"""
        try:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            data = {
                symbol: asdict(info)
                for symbol, info in self._cache.items()
            }
            with open(self._cache_file, 'w') as f:
                json.dump(data, f, indent=2)
            logger.debug(f"Saved leverage cache for {len(self._cache)} pairs")
        except Exception as e:
            logger.error(f"Error saving leverage cache: {e}", exc_info=True)
    
    def get_max_working_leverage(
        self,
        symbol: str,
        api_max_leverage: Optional[float] = None,
        configured_leverage: float = 10.0
    ) -> Optional[float]:
        """
        Get maximum working leverage for a symbol.
        
        Args:
            symbol: Trading pair symbol (e.g., "ADA_USDT")
            api_max_leverage: Maximum leverage reported by API
            configured_leverage: User's configured leverage (default 10x)
        
        Returns:
            Maximum leverage to use (None if margin not viable)
        """
        symbol_upper = symbol.upper()
        current_time = time.time()
        
        # Get cached info
        cached_info = self._cache.get(symbol_upper)
        
        # Check if cache needs verification (once per day)
        needs_verification = False
        if cached_info:
            hours_since_verification = (current_time - cached_info.last_verified) / 3600
            if hours_since_verification >= CACHE_UPDATE_INTERVAL_HOURS:
                needs_verification = True
                logger.info(
                    f"Leverage cache for {symbol_upper} is stale "
                    f"({hours_since_verification:.1f}h old), will verify with next order"
                )
        else:
            # New pair, needs initial verification
            needs_verification = True
        
        # If we have cached working leverage from a REAL order (verified), use it
        # But if it's just the initial conservative value (2x), treat it as "no cache" for first order
        if cached_info and cached_info.max_working_leverage is not None:
            # Check if this is a verified cache (from actual successful order) or just initial value
            # If verification_attempts > 0, it means we've tried at least one order successfully
            is_verified_cache = cached_info.verification_attempts > 0
            
            if is_verified_cache:
                # This is a REAL verified cache - use it and try next step up
                # Use minimum of: cached working leverage, API max, configured
                candidates = [cached_info.max_working_leverage]
                if api_max_leverage:
                    candidates.append(api_max_leverage)
                candidates.append(configured_leverage)
                
                max_working = min(candidates)
                
                # Strategy: Try next step up if possible
                leverage_steps = [2.0, 3.0, 5.0, 10.0]
                next_step = None
                for step in leverage_steps:
                    if step > max_working and step <= configured_leverage:
                        if api_max_leverage is None or step <= api_max_leverage:
                            next_step = step
                            break
                
                if next_step:
                    logger.info(
                        f"Trying higher leverage for {symbol_upper}: {max_working}x → {next_step}x "
                        f"(cached verified working: {max_working}x)"
                    )
                    return next_step
                else:
                    logger.info(
                        f"Using cached verified leverage for {symbol_upper}: {max_working}x "
                        f"(already at maximum)"
                    )
                    return max_working
            else:
                # This is just initial conservative value (not verified yet) - use it as is (2x)
                logger.info(
                    f"Using initial conservative leverage for {symbol_upper}: {cached_info.max_working_leverage}x "
                    f"(not yet verified - will verify with this order)"
                )
                return cached_info.max_working_leverage
        
        # No cache or cache is stale - start with conservative value
        # Strategy: Start with 2x (low) and work up, not start high and work down
        if api_max_leverage and api_max_leverage >= 2.0 and configured_leverage >= 2.0:
            initial_leverage = 2.0  # Start conservative
        elif configured_leverage >= 2.0:
            initial_leverage = 2.0  # Start conservative
        else:
            initial_leverage = min(api_max_leverage or configured_leverage, configured_leverage)
        
        logger.info(
            f"No cached leverage for {symbol_upper}, starting conservative with {initial_leverage}x "
            f"(will increase to 3x, 5x, 10x if successful, api_max={api_max_leverage or 'N/A'}, configured={configured_leverage}x)"
        )
        
        return initial_leverage
    
    def record_leverage_failure(
        self,
        symbol: str,
        attempted_leverage: float,
        error_code: Optional[int] = None
    ):
        """
        Record that a leverage failed (error 306 = INSUFFICIENT_AVAILABLE_BALANCE).
        
        This suggests the leverage was too high for this pair.
        We'll reduce it and try again.
        """
        symbol_upper = symbol.upper()
        
        # Get or create cache entry
        if symbol_upper not in self._cache:
            self._cache[symbol_upper] = PairLeverageInfo(
                symbol=symbol_upper,
                max_working_leverage=None,
                last_verified=time.time(),
                last_failure_leverage=attempted_leverage,
                verification_attempts=0
            )
        else:
            cached_info = self._cache[symbol_upper]
            cached_info.last_failure_leverage = attempted_leverage
        
        logger.warning(
            f"Recorded leverage failure for {symbol_upper}: "
            f"attempted {attempted_leverage}x failed with error {error_code or 306}"
        )
        
        self._save_cache()
    
    def record_leverage_success(
        self,
        symbol: str,
        working_leverage: float
    ):
        """
        Record that a leverage worked successfully.
        
        This becomes the new max_working_leverage for this pair.
        """
        symbol_upper = symbol.upper()
        current_time = time.time()
        
        # Get or create cache entry
        if symbol_upper not in self._cache:
            self._cache[symbol_upper] = PairLeverageInfo(
                symbol=symbol_upper,
                max_working_leverage=working_leverage,
                last_verified=current_time,
                last_failure_leverage=None,
                verification_attempts=1
            )
        else:
            cached_info = self._cache[symbol_upper]
            
            # Strategy: Store the MINIMUM working leverage (not maximum)
            # This way we start low and work up, which is more efficient
            # If 2x works, we'll try 3x next time, then 5x, etc.
            if cached_info.max_working_leverage is None:
                cached_info.max_working_leverage = working_leverage
            else:
                # Keep the minimum working leverage as starting point
                # The system will try higher leverages in subsequent orders
                cached_info.max_working_leverage = min(
                    cached_info.max_working_leverage,
                    working_leverage
                )
            
            cached_info.last_verified = current_time
            cached_info.verification_attempts += 1
        
        logger.info(
            f"Recorded leverage success for {symbol_upper}: "
            f"{working_leverage}x works (max_working={self._cache[symbol_upper].max_working_leverage}x)"
        )
        
        self._save_cache()
    
    def get_next_try_leverage(
        self,
        symbol: str,
        failed_leverage: float,
        min_leverage: float = 1.0
    ) -> Optional[float]:
        """
        Get the next leverage to try after a failure.
        
        Reduces leverage progressively:
        - First failure: reduce by 50%
        - Second failure: reduce by another 50%
        - Continue until we hit min_leverage or SPOT
        
        Args:
            symbol: Trading pair symbol
            failed_leverage: Leverage that just failed
            min_leverage: Minimum leverage to try before giving up (default 1.0 = SPOT)
        
        Returns:
            Next leverage to try, or None if we should use SPOT
        """
        cached_info = self._cache.get(symbol.upper())
        
        if failed_leverage <= min_leverage:
            # Already at minimum, use SPOT
            logger.info(f"{symbol}: Failed leverage {failed_leverage}x is at minimum, using SPOT")
            return None
        
        # Progressive reduction: if leverage fails, reduce it
        # Strategy: Start low (2x), work up. If fails, reduce.
        # If 10x failed -> try 5x, then 3x, then 2x, then SPOT
        # If 5x failed -> try 3x, then 2x, then SPOT
        # If 3x failed -> try 2x, then SPOT
        # If 2x failed -> try SPOT
        
        if failed_leverage >= 10:
            next_leverage = 5.0
        elif failed_leverage >= 5:
            next_leverage = 3.0
        elif failed_leverage >= 3:
            next_leverage = 2.0
        elif failed_leverage >= 2:
            # 2x failed, try SPOT (1x = no margin)
            logger.info(f"{symbol}: Reducing leverage from {failed_leverage}x to SPOT (no margin)")
            return None
        else:
            # Already at 1x or below, use SPOT
            logger.info(f"{symbol}: Failed leverage {failed_leverage}x is at minimum, using SPOT")
            return None
        
        logger.info(
            f"{symbol}: Reducing leverage from {failed_leverage}x to {next_leverage}x "
            f"(progressive reduction)"
        )
        
        return next_leverage
    
    def get_cache_summary(self) -> Dict[str, Dict]:
        """Get summary of leverage cache for debugging"""
        summary = {}
        for symbol, info in self._cache.items():
            hours_ago = (time.time() - info.last_verified) / 3600
            summary[symbol] = {
                "max_working_leverage": info.max_working_leverage,
                "last_verified_hours_ago": round(hours_ago, 1),
                "verification_attempts": info.verification_attempts,
                "last_failure_leverage": info.last_failure_leverage
            }
        return summary


# Global singleton instance
_leverage_cache: Optional[MarginLeverageCache] = None


def get_leverage_cache() -> MarginLeverageCache:
    """Get the global MarginLeverageCache instance"""
    global _leverage_cache
    if _leverage_cache is None:
        _leverage_cache = MarginLeverageCache()
    return _leverage_cache

