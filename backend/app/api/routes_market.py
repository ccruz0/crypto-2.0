from fastapi import APIRouter, Depends, Query
from typing import List, Dict
from app.models.user import User
from app.deps.auth import get_current_user
from app.services.market_data_manager import market_data_manager
from app.services.brokers.base import Exchange
from app.services.signals.signal_engine import evaluate_signals

router = APIRouter()

@router.get("/price")
def get_price(
    exchange: Exchange = Query(..., description="Exchange name"),
    symbol: str = Query(..., description="Symbol (e.g., BTC_USDT)"),
    current_user: User = Depends(get_current_user)
):
    """Get current price from an exchange"""
    price = market_data_manager.get_last_price(exchange, symbol)
    
    return {
        "exchange": exchange,
        "symbol": symbol,
        "price": price
    }

@router.get("/ohlcv")
def get_ohlcv(
    exchange: Exchange = Query(..., description="Exchange name"),
    symbol: str = Query(..., description="Symbol (e.g., BTC_USDT)"),
    interval: str = Query("1h", description="Time interval"),
    limit: int = Query(100, description="Number of candles"),
    current_user: User = Depends(get_current_user)
) -> List[Dict]:
    """Get OHLCV data from an exchange"""
    data = market_data_manager.get_ohlcv(exchange, symbol, interval, limit)
    
    return data

@router.get("/signals")
def get_signals(
    exchange: Exchange = Query(..., description="Exchange name"),
    symbol: str = Query(..., description="Symbol (e.g., BTC_USDT)"),
    current_user: User = Depends(get_current_user)
) -> Dict:
    """Get technical signals for a symbol"""
    signals = evaluate_signals(symbol, exchange)
    return signals
