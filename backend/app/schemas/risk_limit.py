from pydantic import BaseModel, validator
from decimal import Decimal
from datetime import datetime

class RiskLimitIn(BaseModel):
    instrument_id: int
    max_open_orders: int = 1
    max_buy_usd: Decimal = 1000
    allow_margin: bool = False
    max_leverage: Decimal = 1.0
    preferred_exchange: str = "CRYPTO_COM"
    
    @validator('preferred_exchange')
    def validate_exchange(cls, v):
        if v not in ["BINANCE", "CRYPTO_COM"]:
            raise ValueError('preferred_exchange must be "BINANCE" or "CRYPTO_COM"')
        return v
    
    @validator('max_open_orders')
    def validate_max_open_orders(cls, v):
        if v < 0:
            raise ValueError('max_open_orders must be >= 0')
        return v
    
    @validator('max_buy_usd')
    def validate_max_buy_usd(cls, v):
        if v < 0:
            raise ValueError('max_buy_usd must be >= 0')
        return v
    
    @validator('max_leverage')
    def validate_max_leverage(cls, v, values):
        if values.get('allow_margin') and v < 1.0:
            raise ValueError('max_leverage must be >= 1.0 when allow_margin is True')
        return v

class RiskLimitOut(BaseModel):
    id: int
    instrument_id: int
    max_open_orders: int
    max_buy_usd: Decimal
    allow_margin: bool
    max_leverage: Decimal
    preferred_exchange: str
    updated_at: datetime
    
    class Config:
        from_attributes = True
