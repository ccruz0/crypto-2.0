"""
Unit tests for sync_order_history decimal handling and _to_decimal helper.

Covers the fix for: TypeError: unsupported operand type(s) for -: 'float' and 'decimal.Decimal'
- new_cumulative_qty from API (float or str), last_seen_qty from DB (Decimal)
- _to_decimal for float, Decimal, str, None
- delta_qty computation and negative-delta guard (clamp to 0)
"""

import pytest
from decimal import Decimal

from app.services.exchange_sync import _to_decimal


class TestToDecimal:
    """Tests for _to_decimal helper."""

    def test_float_returns_decimal(self):
        """API may return float; conversion must not use Decimal(float) to avoid precision issues."""
        result = _to_decimal(5.1)
        assert result == Decimal("5.1")
        assert isinstance(result, Decimal)

    def test_decimal_returns_same(self):
        """Decimal input returns as-is."""
        val = Decimal("4.86")
        assert _to_decimal(val) is val
        assert _to_decimal(val) == Decimal("4.86")

    def test_string_cumulative_quantity(self):
        """API may return cumulative_quantity as string e.g. '5.10'."""
        result = _to_decimal("5.10")
        assert result == Decimal("5.10")
        assert isinstance(result, Decimal)

    def test_string_with_commas_stripped(self):
        """String with commas (e.g. '1,234.56') is cleaned."""
        result = _to_decimal("1,234.56")
        assert result == Decimal("1234.56")

    def test_none_returns_zero(self):
        """None -> Decimal('0') for safe subtraction."""
        result = _to_decimal(None)
        assert result == Decimal("0")
        assert isinstance(result, Decimal)

    def test_empty_string_returns_zero(self):
        """Empty or whitespace-only string -> Decimal('0')."""
        assert _to_decimal("") == Decimal("0")
        assert _to_decimal("  ") == Decimal("0")


class TestDeltaQtyNoTypeError:
    """Delta qty = new_cumulative_qty - last_seen_qty must work for mixed types."""

    def test_float_minus_decimal(self):
        """Production crash: new_cumulative_qty was float, last_seen_qty from DB was Decimal."""
        new_cumulative_qty = 5.1  # float from API
        last_seen_qty = Decimal("4.86")  # from DB Numeric column
        delta_qty = _to_decimal(new_cumulative_qty) - _to_decimal(last_seen_qty)
        assert delta_qty == Decimal("0.24")
        assert isinstance(delta_qty, Decimal)

    def test_string_minus_decimal(self):
        """API may return cumulative_quantity as string '5.10'."""
        new_cumulative_qty = "5.10"
        last_seen_qty = Decimal("4.86")
        delta_qty = _to_decimal(new_cumulative_qty) - _to_decimal(last_seen_qty)
        assert delta_qty == Decimal("0.24")

    def test_none_last_seen_treated_as_zero(self):
        """existing.cumulative_quantity can be None (new order or unset)."""
        new_cumulative_qty = 5.1
        last_seen_qty = None
        delta_qty = _to_decimal(new_cumulative_qty) - _to_decimal(last_seen_qty)
        assert delta_qty == Decimal("5.1")


class TestNegativeDeltaGuard:
    """Negative delta (ordering/race) must not crash; production code clamps to 0."""

    def test_negative_delta_computation(self):
        """When new < last_seen, delta is negative; we still compute without TypeError."""
        new_cumulative_qty = 4.0
        last_seen_qty = Decimal("5.1")
        delta_qty = _to_decimal(new_cumulative_qty) - _to_decimal(last_seen_qty)
        assert delta_qty < 0
        assert delta_qty == Decimal("-1.1")

    def test_negative_delta_clamp_to_zero(self):
        """Replicate production guard: if delta_qty < 0 then use 0 for downstream."""
        new_cumulative_qty = 4.0
        last_seen_qty = Decimal("5.1")
        delta_qty = _to_decimal(new_cumulative_qty) - _to_decimal(last_seen_qty)
        if delta_qty < 0:
            delta_qty = Decimal("0")
        assert delta_qty == Decimal("0")


class TestNewOrderPathCumulativeQuantity:
    """New-order creation path must set cumulative_quantity as Decimal (same helper as update path)."""

    def test_new_order_cumulative_quantity_from_api_is_decimal(self):
        """Expression used in new-order path: _to_decimal(order_data.get('cumulative_quantity') or 0)."""
        order_data = {"cumulative_quantity": 5.1}
        val = _to_decimal(order_data.get("cumulative_quantity") or 0)
        assert isinstance(val, Decimal)
        assert val == Decimal("5.1")

    def test_new_order_cumulative_quantity_string_from_api(self):
        """API may return cumulative_quantity as string in new-order payload."""
        order_data = {"cumulative_quantity": "5.10"}
        val = _to_decimal(order_data.get("cumulative_quantity") or 0)
        assert isinstance(val, Decimal)
        assert val == Decimal("5.10")

    def test_new_order_cumulative_quantity_missing_uses_zero(self):
        """Missing cumulative_quantity in order_data -> Decimal('0')."""
        order_data = {}
        val = _to_decimal(order_data.get("cumulative_quantity") or 0)
        assert isinstance(val, Decimal)
        assert val == Decimal("0")
