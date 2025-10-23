from pydantic import BaseModel
from decimal import Decimal
from datetime import datetime
from typing import Optional

class PositionOut(BaseModel):
    id: int
    instrument_id: int
    qty: Decimal
    avg_price: Decimal
    is_margin: bool
    leverage: Optional[Decimal]
    updated_at: datetime
    
    class Config:
        from_attributes = True
