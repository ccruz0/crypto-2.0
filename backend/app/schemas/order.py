from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional

class OrderIn(BaseModel):
    instrument_id: int
    side: str  # "BUY" or "SELL"
    type: str  # "MARKET" or "LIMIT"
    price: Decimal
    qty: Decimal
    exchange: str
    is_margin: bool = False
    leverage: Optional[Decimal] = None

class OrderOut(BaseModel):
    id: int
    instrument_id: int
    side: str
    type: str
    price: Decimal
    qty: Decimal
    status: str
    exchange: str
    is_margin: bool
    leverage: Optional[Decimal]
    created_at: datetime
    filled_at: Optional[datetime]
    
    class Config:
        from_attributes = True
