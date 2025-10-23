from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WatchlistIn(BaseModel):
    symbol: str
    exchange: str = "BINANCE"
    buy_target: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None

class WatchlistOut(BaseModel):
    id: int
    symbol: str
    exchange: str
    buy_target: Optional[float]
    take_profit: Optional[float]
    stop_loss: Optional[float]
    order_status: str
    order_date: Optional[datetime]
    purchase_price: Optional[float]
    quantity: Optional[float]
    sold: bool
    sell_price: Optional[float]
    notes: Optional[str]
    created_at: datetime
    
    # Dynamic fields calculated from market data
    price: Optional[float] = None
    rsi: Optional[float] = None
    atr: Optional[float] = None
    ma50: Optional[float] = None
    ma200: Optional[float] = None
    ema10: Optional[float] = None
    res_up: Optional[float] = None
    res_down: Optional[float] = None
    signals: Optional[dict] = None
    
    class Config:
        from_attributes = True
