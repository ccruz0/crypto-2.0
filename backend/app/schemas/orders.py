"""Schemas related to order data."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, Literal, Optional

from pydantic import BaseModel, Field


class UnifiedOpenOrder(BaseModel):
    """
    Represents a normalized open order from the exchange, covering both standard
    limit/market orders and trigger (TP/SL) orders.
    """

    symbol: str
    side: Literal["BUY", "SELL"]
    type: str  # LIMIT, MARKET, TAKE_PROFIT_LIMIT, STOP_LOSS_LIMIT, etc.
    quantity: Decimal

    # Price fields
    price: Optional[Decimal] = None  # Limit price (or execution price)
    trigger_price: Optional[Decimal] = None  # Trigger price for TP/SL

    # Status and Metadata
    status: str  # Raw status from exchange (e.g. "ACTIVE", "NEW")
    is_trigger: bool = Field(default=False, description="True if sourced from get-trigger-orders")

    # Identification
    order_id: str
    client_oid: Optional[str] = None
    created_at: Optional[datetime] = None

    # Debugging/Context
    raw: Dict[str, Any] = Field(default_factory=dict, description="Original payload from exchange")

    class Config:
        extra = "ignore"

