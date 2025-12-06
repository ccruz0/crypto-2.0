"""Schemas for unified open orders exposed by the dashboard API."""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, validator


def _to_decimal(value: Any) -> Decimal:
    """Best-effort conversion to Decimal."""
    try:
        if value is None:
            return Decimal("0")
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


class UnifiedOpenOrder(BaseModel):
    """Normalized representation for both regular and trigger open orders."""

    symbol: str
    side: str
    type: str
    price: Decimal = Field(default_factory=lambda: Decimal("0"))
    trigger_price: Optional[Decimal] = None
    quantity: Decimal = Field(default_factory=lambda: Decimal("0"))
    status: str
    is_trigger: bool = False
    order_id: str
    raw: Dict[str, Any] = Field(default_factory=dict)

    # Validators -----------------------------------------------------------------

    @validator("symbol", "side", "type", "status", pre=True)
    def _upper_strings(cls, value: str) -> str:
        return (value or "").upper()

    @validator("price", "quantity", pre=True)
    def _convert_decimal(cls, value: Any) -> Decimal:
        return _to_decimal(value)

    @validator("trigger_price", pre=True, always=True)
    def _convert_optional_decimal(cls, value: Any) -> Optional[Decimal]:
        if value in (None, "", "0", "0.0", "0.00"):
            return None
        decimal_value = _to_decimal(value)
        return decimal_value if decimal_value != Decimal("0") else None


__all__ = ["UnifiedOpenOrder"]

