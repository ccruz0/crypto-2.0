"""
Portfolio fallback service for local development.

When Crypto.com auth fails, provides portfolio data from alternative sources:
1. Derived from executed orders (trades)
2. Local JSON file
"""

import os
import json
import logging
from typing import Dict, List, Optional, Tuple, Any
from pathlib import Path
from sqlalchemy.orm import Session
from sqlalchemy import func

logger = logging.getLogger(__name__)

# Dust threshold (ignore tiny balances)
DUST_THRESHOLD = 1e-8


def compute_holdings_from_trades(db: Session) -> Dict[str, float]:
    """
    Compute current holdings from executed orders/trades.
    
    Logic:
    - BUY orders add to holdings
    - SELL orders subtract from holdings
    - Ignore dust (< 1e-8)
    
    Returns:
        Dict mapping asset symbol (e.g., "BTC") to total quantity
    """
    holdings = {}
    
    try:
        # Try OrderHistory table first
        from app.models.order_history import OrderHistory
        
        # Get all executed orders (status = FILLED or similar)
        executed_orders = db.query(OrderHistory).filter(
            OrderHistory.status.in_(["FILLED", "FILLED_PARTIALLY", "EXECUTED"])
        ).all()
        
        for order in executed_orders:
            if not order.instrument_name or not order.quantity:
                continue
            
            # Extract base asset from instrument_name (e.g., "BTC_USDT" -> "BTC")
            parts = order.instrument_name.split("_")
            if len(parts) < 2:
                continue
            asset = parts[0].upper()
            quantity = float(order.quantity)
            
            if order.side == "BUY":
                holdings[asset] = holdings.get(asset, 0.0) + quantity
            elif order.side == "SELL":
                holdings[asset] = holdings.get(asset, 0.0) - quantity
        
        # Also check ExchangeOrder table
        try:
            from app.models.exchange_order import ExchangeOrder, OrderStatusEnum
            
            exchange_orders = db.query(ExchangeOrder).filter(
                ExchangeOrder.status.in_([
                    OrderStatusEnum.FILLED,
                    OrderStatusEnum.PARTIALLY_FILLED
                ])
            ).all()
            
            for order in exchange_orders:
                if not order.symbol or not order.quantity:
                    continue
                
                # Extract base asset
                parts = order.symbol.split("_")
                if len(parts) < 2:
                    continue
                asset = parts[0].upper()
                quantity = float(order.quantity)
                
                # Handle enum side
                side_value = order.side.value if hasattr(order.side, 'value') else str(order.side)
                if side_value == "BUY":
                    holdings[asset] = holdings.get(asset, 0.0) + quantity
                elif side_value == "SELL":
                    holdings[asset] = holdings.get(asset, 0.0) - quantity
        except Exception as e:
            logger.debug(f"[PORTFOLIO_FALLBACK] Could not query ExchangeOrder: {e}")
        
        # Filter out dust
        holdings = {asset: qty for asset, qty in holdings.items() if abs(qty) >= DUST_THRESHOLD}
        
        if holdings:
            logger.info(f"[PORTFOLIO_FALLBACK] Computed holdings from trades: {len(holdings)} assets")
        
    except Exception as e:
        logger.warning(f"[PORTFOLIO_FALLBACK] Could not compute holdings from trades: {e}")
        holdings = {}
    
    return holdings


def load_local_portfolio_file() -> Optional[Dict[str, float]]:
    """
    Load portfolio from local JSON file (local dev only).
    
    File location: backend/app/data/local_portfolio.json
    Format: {"BTC": 0.0123, "ETH": 0.5, "USDT": 1200}
    
    Returns:
        Dict mapping asset to quantity, or None if file doesn't exist
    """
    # Only in local environment
    if os.getenv("ENVIRONMENT") != "local" and os.getenv("RUNTIME_ORIGIN") != "LOCAL":
        return None
    
    file_path = Path(__file__).parent.parent / "data" / "local_portfolio.json"
    
    if not file_path.exists():
        return None
    
    try:
        with open(file_path, 'r') as f:
            data = json.load(f)
        
        # Validate format
        if not isinstance(data, dict):
            logger.warning(f"[PORTFOLIO_FALLBACK] Invalid format in {file_path}")
            return None
        
        # Convert to float and filter dust
        holdings = {}
        for asset, qty in data.items():
            try:
                qty_float = float(qty)
                if abs(qty_float) >= DUST_THRESHOLD:
                    holdings[asset.upper()] = qty_float
            except (ValueError, TypeError):
                logger.warning(f"[PORTFOLIO_FALLBACK] Invalid quantity for {asset}: {qty}")
        
        if holdings:
            logger.info(f"[PORTFOLIO_FALLBACK] Loaded {len(holdings)} assets from {file_path}")
        
        return holdings
        
    except Exception as e:
        logger.warning(f"[PORTFOLIO_FALLBACK] Could not load local portfolio file: {e}")
        return None


def get_fallback_holdings(db: Session) -> Tuple[Optional[Dict[str, float]], str]:
    """
    Get fallback holdings from available sources.
    
    Priority:
    1. Derived from trades (if available)
    2. Local JSON file (if exists)
    
    Returns:
        Tuple of (holdings dict, source name)
        Returns (None, "") if no fallback available
    """
    # Try trades first
    holdings = compute_holdings_from_trades(db)
    if holdings:
        return holdings, "derived_trades"
    
    # Try local file
    holdings = load_local_portfolio_file()
    if holdings:
        return holdings, "local_file"
    
    return None, ""


def get_price_for_asset(asset: str) -> Tuple[Optional[float], str]:
    """
    Get USD price for an asset with fallback sources.
    
    Priority:
    1. CoinGecko
    2. Yahoo Finance (via simple_price_fetcher)
    3. Stablecoin check (USDT/USDC = 1.0)
    4. None if all fail
    
    Returns:
        Tuple of (price, source_name)
    """
    asset_upper = asset.upper()
    
    # Stablecoins
    if asset_upper in ["USDT", "USDC", "USD"]:
        return 1.0, "stablecoin"
    
    # Try CoinGecko
    try:
        from simple_price_fetcher import SimplePriceFetcher
        price_fetcher = SimplePriceFetcher()
        
        # Try with _USDT suffix first
        result = price_fetcher.get_price(f"{asset_upper}_USDT")
        if result and result.success and result.price and result.price > 0:
            return result.price, "coingecko"
        
        # Try without suffix
        result = price_fetcher.get_price(asset_upper)
        if result and result.success and result.price and result.price > 0:
            return result.price, "coingecko"
    except Exception as e:
        logger.debug(f"[PORTFOLIO_FALLBACK] CoinGecko failed for {asset}: {e}")
    
    # Try Yahoo Finance (if available in price_fetcher)
    try:
        from simple_price_fetcher import SimplePriceFetcher
        price_fetcher = SimplePriceFetcher()
        # Yahoo Finance might be available as a fallback in the fetcher
        # This depends on the implementation
        result = price_fetcher.get_price(asset_upper, source="yahoo")
        if result and result.success and result.price and result.price > 0:
            return result.price, "yahoo"
    except Exception as e:
        logger.debug(f"[PORTFOLIO_FALLBACK] Yahoo Finance failed for {asset}: {e}")
    
    return None, "none"


def build_fallback_positions(db: Session, holdings: Dict[str, float], source: str) -> List[Dict[str, Any]]:
    """
    Build positions array from fallback holdings with prices.
    
    Args:
        db: Database session
        holdings: Dict mapping asset to quantity
        source: Source name (e.g., "derived_trades", "local_file")
    
    Returns:
        List of position dicts with asset, free, locked, total, price_usd, value_usd, price_source
    """
    positions = []
    errors = []
    
    for asset, quantity in holdings.items():
        if quantity <= 0:
            continue
        
        # Get price
        price_usd, price_source = get_price_for_asset(asset)
        
        if price_usd is None or price_usd <= 0:
            errors.append(f"missing_price: {asset}")
            price_usd = 0.0
            price_source = "none"
        
        value_usd = quantity * price_usd
        
        positions.append({
            "asset": asset,
            "free": quantity,  # Assume all is free for fallback
            "locked": 0.0,
            "total": quantity,
            "price_usd": price_usd,
            "value_usd": value_usd,
            "source": source,
            "price_source": price_source
        })
    
    if errors:
        logger.warning(f"[PORTFOLIO_FALLBACK] Price errors: {errors}")
    
    return positions

