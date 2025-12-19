"""Utilities for working with unified open orders (regular + trigger)."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, Field


def _safe_decimal(value: Any) -> Optional[Decimal]:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        if isinstance(value, (int, float)):
            return Decimal(str(value))
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _normalize_symbol(symbol: Optional[str]) -> str:
    if not symbol:
        return ""
    return symbol.replace("-", "_").replace("/", "_").upper()


def _extract_base_symbol(symbol: str) -> str:
    symbol = _normalize_symbol(symbol)
    if "_" in symbol:
        return symbol.split("_", 1)[0]
    if "-" in symbol:
        return symbol.split("-", 1)[0]
    if symbol.endswith("USDT"):
        return symbol[:-4]
    if symbol.endswith("USD"):
        return symbol[:-3]
    return symbol


def _format_timestamp(value: Any) -> Optional[str]:
    if value in (None, "", 0):
        return None
    try:
        if isinstance(value, datetime):
            return value.astimezone(timezone.utc).isoformat()
        if isinstance(value, (int, float)):
            ts = float(value)
            if ts > 10_000_000_000:
                ts /= 1000.0
            return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
        value_str = str(value).strip()
        if not value_str:
            return None
        if value_str.endswith("Z"):
            value_str = value_str[:-1] + "+00:00"
        parsed = datetime.fromisoformat(value_str)
        return parsed.astimezone(timezone.utc).isoformat()
    except Exception:
        return None


class UnifiedOpenOrder(BaseModel):
    """Representation for both regular and trigger open orders."""

    order_id: str
    symbol: str
    side: str
    order_type: str = "LIMIT"
    status: str = "NEW"
    price: Optional[Decimal] = None
    trigger_price: Optional[Decimal] = None
    quantity: Decimal = Field(default_factory=lambda: Decimal("0"))
    is_trigger: bool = False
    trigger_type: Optional[str] = None
    trigger_condition: Optional[str] = None
    client_oid: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
    source: str = "standard"
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

    @property
    def base_symbol(self) -> str:
        return _extract_base_symbol(self.symbol)

    def price_as_float(self) -> Optional[float]:
        for candidate in (self.trigger_price, self.price):
            if candidate is not None:
                return float(candidate)
        return None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id,
            "exchange_order_id": self.order_id,
            "symbol": self.symbol,
            "base_symbol": self.base_symbol,
            "side": self.side,
            "order_type": self.order_type,
            "status": self.status,
            "price": float(self.price) if self.price is not None else None,
            "trigger_price": float(self.trigger_price) if self.trigger_price is not None else None,
            "quantity": float(self.quantity),
            "is_trigger": self.is_trigger,
            "trigger_type": self.trigger_type,
            "trigger_condition": self.trigger_condition,
            "client_oid": self.client_oid,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "source": self.source,
            "raw": self.metadata,
        }


def serialize_unified_order(order: UnifiedOpenOrder) -> Dict[str, Any]:
    """Return the public dictionary representation of a unified order."""
    return order.to_public_dict()


def _build_unified_order(order: Dict[str, Any], is_trigger: bool) -> Optional[UnifiedOpenOrder]:
    order_id = str(order.get("order_id") or order.get("id") or order.get("client_oid") or "").strip()
    if not order_id:
        return None

    symbol = _normalize_symbol(order.get("instrument_name") or order.get("symbol"))
    side = (order.get("side") or "").upper() or "BUY"
    order_type = (order.get("order_type") or order.get("type") or ("TRIGGER" if is_trigger else "LIMIT")).upper()

    price = _safe_decimal(order.get("limit_price") or order.get("price"))
    trigger_price = _safe_decimal(order.get("trigger_price") or order.get("stop_price") or order.get("stop_limit_price"))
    quantity = _safe_decimal(order.get("quantity") or order.get("order_amount") or order.get("size")) or Decimal("0")

    return UnifiedOpenOrder(
        order_id=order_id,
        symbol=symbol,
        side=side,
        order_type=order_type,
        status=(order.get("status") or "NEW").upper(),
        price=price,
        trigger_price=trigger_price,
        quantity=quantity,
        is_trigger=is_trigger,
        trigger_type=order.get("trigger_type") or order.get("trigger_by"),
        trigger_condition=order.get("trigger_condition"),
        client_oid=order.get("client_oid"),
        created_at=_format_timestamp(order.get("create_time") or order.get("created_at")),
        updated_at=_format_timestamp(order.get("update_time") or order.get("updated_at")),
        source="trigger" if is_trigger else "standard",
        metadata=order,
    )


def merge_orders(
    regular_orders: Iterable[Dict[str, Any]],
    trigger_orders: Iterable[Dict[str, Any]],
) -> List[UnifiedOpenOrder]:
    """Merge regular and trigger open orders, deduplicating by order_id."""
    merged: Dict[str, UnifiedOpenOrder] = {}

    def upsert(unified: Optional[UnifiedOpenOrder]) -> None:
        if unified is None:
            return
        existing = merged.get(unified.order_id)
        if not existing:
            merged[unified.order_id] = unified
            return
        if unified.is_trigger and not existing.is_trigger:
            merged[unified.order_id] = unified
            return

        def richness(order: UnifiedOpenOrder) -> int:
            score = 0
            for attr in ("trigger_price", "price", "trigger_type", "client_oid"):
                if getattr(order, attr):
                    score += 1
            return score

        if richness(unified) > richness(existing):
            merged[unified.order_id] = unified

    for raw in regular_orders or []:
        upsert(_build_unified_order(raw, False))
    for raw in trigger_orders or []:
        upsert(_build_unified_order(raw, True))

    result = list(merged.values())
    result.sort(key=lambda o: (o.symbol, o.created_at or "", o.order_id))
    return result


def calculate_portfolio_order_metrics(
    orders: Iterable[UnifiedOpenOrder],
    market_prices: Optional[Dict[str, float]] = None,
) -> Dict[str, Dict[str, Optional[float]]]:
    """Calculate per-symbol metrics for open orders."""
    metrics: Dict[str, Dict[str, Optional[float]]] = {}
    market_prices = market_prices or {}

    for order in orders or []:
        base = order.base_symbol
        if not base:
            continue
        entry = metrics.setdefault(base, {"open_orders_count": 0, "tp": None, "sl": None})
        
        # Only count BUY orders (open positions), not SELL orders (TP/SL)
        # SELL orders are TP/SL protection orders, not open positions
        if order.side == "BUY":
            entry["open_orders_count"] = (entry["open_orders_count"] or 0) + 1

        if order.side != "SELL":
            continue

        price = order.price_as_float()
        if price is None:
            continue

        market_price = market_prices.get(base)
        order_type = order.order_type.upper()
        trigger_type = (order.trigger_type or "").upper()
        
        # Check metadata for order_role (from database orders)
        order_role = None
        if order.metadata:
            order_role = (order.metadata.get("order_role") or order.metadata.get("role") or "").upper()

        # Identify TP orders: check order_type, trigger_type, and order_role
        is_tp = (
            "TAKE_PROFIT" in order_type or
            "TAKE_PROFIT" in trigger_type or
            order_role == "TAKE_PROFIT"
        )
        
        # Identify SL orders: check order_type, trigger_type, and order_role
        is_sl = (
            "STOP_LOSS" in order_type or
            "STOP_LOSS" in trigger_type or
            order_role == "STOP_LOSS" or
            ("STOP" in order_type and "LOSS" not in order_type and "LIMIT" not in order_type) or
            ("STOP" in trigger_type and "LOSS" not in trigger_type)
        )

        if market_price is not None:
            # Use market price comparison as primary method
            if price > market_price:
                # Above market = TP
                entry["tp"] = price if entry["tp"] is None else max(entry["tp"], price)
            elif price < market_price:
                # Below market = SL
                entry["sl"] = price if entry["sl"] is None else min(entry["sl"], price)
        else:
            # Fallback to order type/role identification when market price unavailable
            if is_tp:
                entry["tp"] = price if entry["tp"] is None else max(entry["tp"], price)
            elif is_sl:
                entry["sl"] = price if entry["sl"] is None else min(entry["sl"], price)

    return metrics
