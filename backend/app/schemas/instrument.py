from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional

class InstrumentIn(BaseModel):
    symbol: str
    venue: str  # "CRYPTO" or "STOCK"
    tick_size: Optional[Decimal] = None
    lot_size: Optional[Decimal] = None

class InstrumentOut(BaseModel):
    id: int
    symbol: str
    venue: str
    tick_size: Optional[Decimal]
    lot_size: Optional[Decimal]
    created_at: datetime
    
    class Config:
        from_attributes = True
