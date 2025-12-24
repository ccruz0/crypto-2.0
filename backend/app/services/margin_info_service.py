"""
Margin Information Service

Fetches and caches margin trading capabilities per instrument from Crypto.com Exchange.
This prevents error 306 by ensuring we never request leverage higher than the maximum allowed.
"""
import logging
import time
from typing import Optional, Dict
from dataclasses import dataclass
from app.utils.http_client import http_get, http_post

logger = logging.getLogger(__name__)

# Cache TTL: 15 minutes (instruments don't change frequently)
CACHE_TTL_SECONDS = 15 * 60


@dataclass
class MarginInfo:
    """Margin trading information for an instrument"""
    margin_trading_enabled: bool
    max_leverage: Optional[float]  # None if margin not enabled
    instrument_name: str
    cached_at: float


class MarginInfoService:
    """Service to fetch and cache margin capabilities per instrument"""
    
    def __init__(self):
        self._cache: Dict[str, MarginInfo] = {}
        self._last_fetch_time: float = 0
        self._all_instruments: Optional[list] = None
        self._instruments_url = "https://api.crypto.com/exchange/v1/public/get-instruments"
    
    def _fetch_all_instruments(self) -> Optional[list]:
        """Fetch all instruments from Crypto.com Exchange API"""
        current_time = time.time()
        
        # Use cached instruments if still fresh
        if self._all_instruments and (current_time - self._last_fetch_time) < CACHE_TTL_SECONDS:
            return self._all_instruments
        
        try:
            logger.debug(f"Fetching instruments from {self._instruments_url}")
            response = http_get(self._instruments_url, timeout=10, calling_module="margin_info_service")
            response.raise_for_status()
            data = response.json()
            
            # Crypto.com API v1 structure: result.data (not result.instruments)
            instruments = None
            if "result" in data:
                if "data" in data["result"]:
                    instruments = data["result"]["data"]
                elif "instruments" in data["result"]:
                    instruments = data["result"]["instruments"]
            
            if instruments:
                self._all_instruments = instruments
                self._last_fetch_time = current_time
                logger.info(f"✅ Fetched {len(instruments)} instruments from Crypto.com")
                return instruments
            else:
                logger.warning("No instruments found in API response")
                return None
                
        except Exception as e:
            logger.error(f"Error fetching instruments: {e}", exc_info=True)
            # Return cached data if available, even if stale
            if self._all_instruments:
                logger.warning(f"Using stale instruments cache due to fetch error")
                return self._all_instruments
            return None
    
    def get_margin_info_for_symbol(self, symbol: str) -> MarginInfo:
        """
        Get margin information for a given symbol.
        
        Returns MarginInfo with:
        - margin_trading_enabled: bool
        - max_leverage: Optional[float] (None if margin not enabled)
        - instrument_name: str
        - cached_at: float
        
        Uses in-memory cache with TTL to avoid hammering the API.
        """
        # Normalize symbol (uppercase, ensure format matches API)
        symbol_upper = symbol.upper()
        
        # Check cache first
        if symbol_upper in self._cache:
            cached_info = self._cache[symbol_upper]
            cache_age = time.time() - cached_info.cached_at
            
            if cache_age < CACHE_TTL_SECONDS:
                logger.debug(f"Using cached margin info for {symbol_upper}: max_leverage={cached_info.max_leverage}")
                return cached_info
            else:
                logger.debug(f"Cache expired for {symbol_upper} (age: {cache_age:.0f}s), refreshing...")
        
        # Fetch fresh data
        instruments = self._fetch_all_instruments()
        
        if not instruments:
            # Fallback: return default (no margin) if we can't fetch
            logger.warning(f"Could not fetch instruments, returning default (no margin) for {symbol_upper}")
            default_info = MarginInfo(
                margin_trading_enabled=False,
                max_leverage=None,
                instrument_name=symbol_upper,
                cached_at=time.time()
            )
            self._cache[symbol_upper] = default_info
            return default_info
        
        # Find matching instrument
        # Crypto.com API v1 uses "symbol" field (e.g., "ADA_USDT"), not "instrument_name"
        matching_instrument = None
        for inst in instruments:
            # Try both "symbol" and "instrument_name" fields
            inst_symbol = inst.get("symbol", "").upper()
            inst_name = inst.get("instrument_name", "").upper()
            if inst_symbol == symbol_upper or inst_name == symbol_upper:
                matching_instrument = inst
                break
        
        if not matching_instrument:
            logger.warning(f"Instrument {symbol_upper} not found in API response")
            # Return default (no margin) for unknown instruments
            default_info = MarginInfo(
                margin_trading_enabled=False,
                max_leverage=None,
                instrument_name=symbol_upper,
                cached_at=time.time()
            )
            self._cache[symbol_upper] = default_info
            return default_info
        
        # Extract margin information
        # Crypto.com API v1 uses:
        # - "margin_buy_enabled" and "margin_sell_enabled" (boolean)
        # - "max_leverage" (string like "5" or "10")
        margin_trading_enabled = False
        max_leverage = None
        
        # Check if margin is enabled (either buy or sell)
        margin_buy_enabled = matching_instrument.get("margin_buy_enabled", False)
        margin_sell_enabled = matching_instrument.get("margin_sell_enabled", False)
        margin_trading_enabled = bool(margin_buy_enabled or margin_sell_enabled)
        
        # Also check legacy field names for compatibility
        if not margin_trading_enabled:
            if "margin_trading_enabled" in matching_instrument:
                margin_trading_enabled = bool(matching_instrument["margin_trading_enabled"])
            elif "margin_trading" in matching_instrument:
                margin_trading_enabled = bool(matching_instrument["margin_trading"])
        
        # Extract max leverage (API returns as string)
        if "max_leverage" in matching_instrument:
            max_leverage_val = matching_instrument["max_leverage"]
            if max_leverage_val is not None:
                try:
                    # API returns as string, convert to float
                    max_leverage = float(str(max_leverage_val))
                except (ValueError, TypeError):
                    max_leverage = None
        
        # Create and cache the result
        margin_info = MarginInfo(
            margin_trading_enabled=margin_trading_enabled,
            max_leverage=max_leverage,
            instrument_name=symbol_upper,
            cached_at=time.time()
        )
        
        self._cache[symbol_upper] = margin_info
        
        logger.info(
            f"✅ Margin info for {symbol_upper}: enabled={margin_trading_enabled}, "
            f"max_leverage={max_leverage}"
        )
        
        return margin_info
    
    def clear_cache(self):
        """Clear the cache (useful for testing or forced refresh)"""
        self._cache.clear()
        self._all_instruments = None
        self._last_fetch_time = 0
        logger.info("Margin info cache cleared")


# Global singleton instance
_margin_info_service: Optional[MarginInfoService] = None


def get_margin_info_service() -> MarginInfoService:
    """Get the global MarginInfoService instance"""
    global _margin_info_service
    if _margin_info_service is None:
        _margin_info_service = MarginInfoService()
    return _margin_info_service


def get_margin_info_for_symbol(symbol: str) -> MarginInfo:
    """
    Convenience function to get margin info for a symbol.
    
    Usage:
        margin_info = get_margin_info_for_symbol("ADA_USDT")
        if margin_info.margin_trading_enabled:
            max_lev = margin_info.max_leverage  # e.g., 5.0
    """
    service = get_margin_info_service()
    return service.get_margin_info_for_symbol(symbol)

