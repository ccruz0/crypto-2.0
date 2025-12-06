from pydantic import BaseModel
from typing import Optional
from datetime import datetime

class WatchlistItemBase(BaseModel):
    symbol: str
    exchange: str
    buy_target: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    trade_enabled: Optional[bool] = False
    trade_amount_usd: Optional[float] = None
    trade_on_margin: Optional[bool] = False
    sl_tp_mode: Optional[str] = "conservative"
    sl_percentage: Optional[float] = None
    tp_percentage: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None

class WatchlistItemCreate(WatchlistItemBase):
    pass

class WatchlistItemUpdate(BaseModel):
    symbol: Optional[str] = None
    exchange: Optional[str] = None
    buy_target: Optional[float] = None
    take_profit: Optional[float] = None
    stop_loss: Optional[float] = None
    trade_enabled: Optional[bool] = None
    trade_amount_usd: Optional[float] = None
    trade_on_margin: Optional[bool] = None
    alert_enabled: Optional[bool] = None  # Enable automatic alerts and order creation
    sl_tp_mode: Optional[str] = None
    sl_percentage: Optional[float] = None
    tp_percentage: Optional[float] = None

class WatchlistItemResponse(WatchlistItemBase):
    id: int
    trade_enabled: Optional[bool] = False
    trade_amount_usd: Optional[float] = None
    trade_on_margin: Optional[bool] = False
    sl_tp_mode: Optional[str] = "conservative"
    sl_percentage: Optional[float] = None
    tp_percentage: Optional[float] = None
    sl_price: Optional[float] = None
    tp_price: Optional[float] = None
    order_status: str
    order_date: Optional[datetime] = None
    purchase_price: Optional[float] = None
    quantity: Optional[float] = None
    sold: bool
    sell_price: Optional[float] = None
    notes: Optional[str] = None
    created_at: datetime
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

